import time
from core.recalibrate import recalibrate
from core.player_profile import get_gather_node_level, set_gather_node_level

from core.core import (
    req_ocr,
    req_text,
    tap_on_text,
    req_temp_match,
    tap_on_template,
    tap_on_templates_batch
)
from cmd_program.screen_action import(
    tap_screen,
    swipe_screen,
    input_text
)




def enter_world_map(max_attempts=4):
    """Verified world-map entry. The World/City toggle drops taps that land
    during the zoom animation, so tap-then-assume races and the rest of the
    task then runs against the city view. Read, tap, settle, re-read."""
    for _ in range(max_attempts):
        time.sleep(0.5)
        title = req_text("World.City")
        try:
            if title[0][0].lower() == "city":
                return True
        except Exception:
            pass
        recalibrate()
        tap_on_text("Home.World", wait=2)
        time.sleep(3)
    return False


def wait_till_return(lowest_time=14400):
    recalling = recall_current_gathering(lowest_time=lowest_time)
    while(recalling):
        time.sleep(0.5)
        return_times = req_text(
                [
                "World.FirstMarchTime",
                "World.SecondMarchTime",
                "World.ThirdMarchTime", 
                "World.FourthMarchTime", 
                "World.FifthMarchTime"
            ]
        )
        times = []
        for i, return_time in enumerate(return_times):
            try:
                return_time = return_time[0].split(':')
                return_time = [int(t) for t in return_time]
                return_time = return_time[0]*3600 + return_time[1]*60 + return_time[2]
                times.append(return_time)
            except Exception as e:
                print(f"Couldn't read the time properly - {e}")

        if len(times) <= 1:
            break

        waiting_time = max(times) if len(times)>0 else 0
        if waiting_time > 600:
            recalling = recall_current_gathering(lowest_time=lowest_time)
            continue
        elif waiting_time == 0:
            recalling = False
            break
        print(f"Waiting for {waiting_time} seconds for the troops to return home...")
        time.sleep(waiting_time)



def _no_suitable_resource_shown():
    """Full-frame OCR check for the game's 'no suitable resource' toast, shown
    when a search finds no node at the requested level near this account."""
    results = req_ocr(rois=None, name="gather.no_suitable_resource")
    for item in results or []:
        text = item.get("text", "").lower()
        if "suitable" in text or "no resource" in text:
            return True
    return False


def _set_search_level(level):
    tap_screen(84.26, 86.22)
    time.sleep(1)
    input_text(str(level))


def gather(remove_hero=False, equalize=True, lowest_time=14400, node_level=None,
           profile=None):
    print("Started Gathering...")
    search_box = [[0, 78.86, 100, 80.49]]
    gathering_nodes = ["meat", "wood", "coal", "iron", "coal", "iron"]
    if node_level is None:
        node_level = get_gather_node_level(profile) if profile else 8
    node_level = int(node_level)

    if not enter_world_map():
        print("Couldn't reach the world map, Exiting the task...")
        return

    wait_till_return(lowest_time=lowest_time)

    try:
        time.sleep(0.5)
        data = req_text('World.MarchQueue')[0][0].split('/')
        remaining_march = int(data[1]) - int(data[0])
        occupied_march = int(data[0])
    except Exception as e:
        print(f"Reading Error - {e}")
        remaining_march = 4
        occupied_march = 0
    i = 0
    
    while remaining_march>0 and occupied_march < 5:
        title = tap_on_text("World.City", tap=False)
        if not title:
            tap_screen(50.93, 50.41)
            time.sleep(0.5)
        print(f"Remaining march queue: {remaining_march} ----- Occupied March: {occupied_march}")
        if occupied_march == 5:
            break
        status = tap_on_template("World.Search", wait=2, threshold=0.6)
        if not status:
            print("Seach Icon not found, Exiting the task...")
            return
        found = tap_on_text(gathering_nodes[i], rois=search_box, wait=2)
        if found is None:
            swipe_screen(92.59, 78.05, 0, 78.05)
            tap_on_text(gathering_nodes[i], rois=search_box, wait=2)
        # time.sleep(0.5)             #rapid tap between node and search cause friction
        
        time.sleep(0.5)
        level = req_text("World.Search.ItemLevel")
        try:
            level = level[0][0]
            if level != str(node_level):
                _set_search_level(node_level)
        except Exception as e:
            print(f"Level reading Error, Continuing without reading the level...")

        # from here its needs to be optimized
        status = tap_on_text("World.Search.Search", wait=2)
        if status:
            status = tap_on_text("World.Search.Gather", wait=5)
            if not status:
                # Adapt to the account: when the game says no suitable
                # resource at this level, step down and retry the same node
                # instead of cycling node types at a level that cannot work.
                if node_level > 1 and _no_suitable_resource_shown():
                    node_level -= 1
                    print(f"No suitable resource, lowering node level to {node_level}")
                    if profile:
                        set_gather_node_level(profile, node_level)
                    _set_search_level(node_level)
                    continue
                i += 1
                if i>=5:
                    i = 0
                continue
        if not status:
            print("Gather button is not found, Exiting the task...")
            return
        if remove_hero:
            tap_on_template("World.Deploy.RemoveHero", threshold=0.6, rois=[[27.78, 20.33, 37.04, 26.42]], wait=2)  # removing hero
        if equalize:
            tap_on_text("World.Deploy.Equalize", wait=2)
        tap_on_text("World.Deploy.Deploy", wait=2, sleep=0.5)
        # A deploy at this level worked — remember it so the next run
        # starts here instead of rediscovering it.
        if profile:
            set_gather_node_level(profile, node_level)

        i = i+1
        if i>=5:
            i = 0

        try:
            time.sleep(0.5)
            data = req_text('World.MarchQueue')[0][0].split('/')
            remaining_march = int(data[1]) - int(data[0])
            occupied_march = int(data[0])
        except Exception as e:
            print(f"Reading Error - {e}")
            remaining_march = remaining_march - 1
    
    time.sleep(0.5)
    text = req_text("World.City")
    try:
        text = text[0][0]
        if text.lower() != "city":
            tap_screen(50.93, 50)
    except Exception as e:
        print("The search tab may still opened, Trying to recover...")
    print("Completed the gathering task, Returning to homepage...")
    recalibrate()




def recall_current_gathering(lowest_time=14400):
    recalling = False
    if not enter_world_map():
        print("Couldn't reach the world map, Skipping the recall check...")
        return False

    time.sleep(0.5)
    march_time = req_text("World.FirstMarchTime")
    try:
        march_time = march_time[0][0].split(':')
        march_time = [int(t) for t in march_time]
        march_time = march_time[0]*3600 + march_time[1]*60 + march_time[2]
    except Exception as e:
        print(f"Couldn't read the time properly - {e}")
    
    if not isinstance(march_time, int) or march_time < lowest_time:
        found = True
        recalling = True
        while found:
            found = tap_on_template("World.Recall", threshold = 0.95, wait=2, sleep=0.5)
            tap_on_text("World.Recall.Confirm", wait=2, sleep=1)
    
    return recalling
            

