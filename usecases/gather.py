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




def _on_world_map():
    title = req_text("World.City")
    try:
        return title[0][0].lower() == "city"
    except Exception:
        return False


def enter_world_map(max_attempts=4):
    """Verified world-map entry. The World/City toggle drops taps that land
    during the zoom animation, so tap-then-assume races and the rest of the
    task then runs against the city view. Read, tap, settle, re-read — and
    verify once more after the last tap, so the final attempt is never an
    unchecked tap-and-give-up."""
    for _ in range(max_attempts):
        time.sleep(0.5)
        if _on_world_map():
            return True
        recalibrate()
        tap_on_text("Home.World", wait=2)
        time.sleep(3)
    return _on_world_map()


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



# World-map coordinate bar ("#4653 X:1019 Y:308"), measured live at 1080x2460.
MAP_COORDS_ROI = [[25, 85.2, 70, 89.0]]


def _read_map_coords():
    """Read the world-map coordinate bar. A successful search jumps the camera
    (coords change); 'No suitable resources' leaves it in place — that camera
    jump is the reliable found/not-found signal, not the transient toast."""
    results = req_ocr(rois=MAP_COORDS_ROI, name="gather.map_coords", read_kind="value")
    for item in results or []:
        text = item.get("text", "")
        if "X:" in text or "Y:" in text:
            return text.strip()
    return None


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
        if profile:
            # Probe one level above the remembered one: the stored level only
            # ever steps down during a run, so without this the profile could
            # never recover upward as the account grows. Costs at most one
            # failed search per run when the stored level is already right.
            node_level = min(get_gather_node_level(profile) + 1, 8)
        else:
            node_level = 8
    node_level = int(node_level)

    if not enter_world_map():
        print("Couldn't reach the world map, Exiting the task...")
        return

    wait_till_return(lowest_time=lowest_time)

    try:
        time.sleep(0.5)
        data = req_text('World.MarchQueue', read_kind="value")[0][0].split('/')
        remaining_march = int(data[1]) - int(data[0])
        occupied_march = int(data[0])
    except Exception as e:
        print(f"Reading Error - {e}")
        remaining_march = 4
        occupied_march = 0
    i = 0
    
    indeterminate = 0
    while remaining_march>0 and occupied_march < 5:
        title = tap_on_text("World.City", tap=False)
        if not title:
            tap_screen(50.93, 50.41)
            time.sleep(0.5)
        print(f"Remaining march queue: {remaining_march} ----- Occupied March: {occupied_march}")
        if occupied_march == 5:
            break
        coords_before = _read_map_coords()
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
        # level_confirmed gates profile persistence on deploy: the +1 upward
        # probe must never be recorded unless the UI verifiably shows it —
        # otherwise OCR failures ratchet the stored level upward.
        level_confirmed = False
        try:
            level = req_text("World.Search.ItemLevel", read_kind="value")[0][0]
            if level != str(node_level):
                _set_search_level(node_level)
                time.sleep(0.5)
                recheck = req_text("World.Search.ItemLevel", read_kind="value")
                level_confirmed = recheck[0][0] == str(node_level)
            else:
                level_confirmed = True
        except Exception as e:
            print(f"Level reading Error, Continuing without reading the level...")

        # from here its needs to be optimized
        status = tap_on_text("World.Search.Search", wait=2)
        if status:
            status = tap_on_text("World.Search.Gather", wait=5)
            if not status:
                # No Gather button. If the camera provably never jumped, the
                # search found nothing at this level ('No suitable resources')
                # — step the level down and retry. Lowering needs POSITIVE
                # evidence (both coordinate reads valid and equal): a None
                # read is an OCR flake, not proof the camera stayed, and a
                # flake-driven decrement would persist to the profile and
                # ratchet every account toward level 1 over long runs.
                coords_after = _read_map_coords()
                stayed = (coords_before is not None
                          and coords_after is not None
                          and coords_after == coords_before)
                if stayed and node_level > 1:
                    node_level -= 1
                    indeterminate = 0
                    print(f"Search didn't move the camera, lowering node level to {node_level}")
                    # Persist only when the UI verifiably showed the level that
                    # was searched (level_confirmed) — an unconfirmed search may
                    # have run at a stale field value, so attributing the miss
                    # to node_level would persist a bogus decrement (red-team).
                    if profile and level_confirmed:
                        set_gather_node_level(profile, node_level)
                    continue
                if coords_before is None or coords_after is None:
                    # No evidence either way. Without a bound this loops
                    # forever at an unusable level when the coordinate bar
                    # keeps failing to OCR: after 3 indeterminate misses,
                    # fall back one level for THIS RUN ONLY (not persisted —
                    # persistence needs positive evidence or a deploy).
                    indeterminate += 1
                    if indeterminate >= 3 and node_level > 1:
                        node_level -= 1
                        indeterminate = 0
                        print(f"No camera evidence 3x, trying level {node_level} this run (not persisted)")
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
        # A deploy worked — remember the level so the next run starts here,
        # but only when the UI verifiably showed this level (level_confirmed);
        # otherwise the deploy may have used the field's previous value.
        if profile and level_confirmed:
            set_gather_node_level(profile, node_level)

        i = i+1
        if i>=5:
            i = 0

        try:
            time.sleep(0.5)
            data = req_text('World.MarchQueue', read_kind="value")[0][0].split('/')
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
            

