import time
from core.recalibrate import recalibrate

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
# use percentages directly; screen_action will convert per-device




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



def gather(remove_hero=False, equalize=True, lowest_time=14400):
    print("Started Gathering...")
    search_box = [[0, 78.86, 100, 80.49]]
    gathering_nodes = ["meat", "wood", "coal", "iron", "coal", "iron"]

    time.sleep(0.5)
    title = req_text("World.City")
    try:
        title = title[0][0].lower()
    except Exception as e:
        print(f"Reading Error - {e}")
    if title != "city":
        recalibrate()
        tap_on_text("Home.World", wait=2)

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
            if level != "8":
                tap_screen(84.26, 86.22)
                time.sleep(1)
                input_text("8")
        except Exception as e:
            print(f"Level reading Error, Continuing without reading the level...")

        # from here its needs to be optimized
        status = tap_on_text("World.Search.Search", wait=2)
        if status:
            status = tap_on_text("World.Search.Gather", wait=5)
            if not status:
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
    time.sleep(0.5)
    title = req_text("World.City")
    recalling = False
    try:
        title = title[0][0].lower()
    except Exception as e:
        print(f"Reading Error - {e}")
    if title != "city":
        recalibrate()
        tap_on_text("Home.World", sleep=2)
    
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
            

