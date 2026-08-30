#coming soon
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




parallel = True


def recall_current_march(lowest_time=14400):
    title = req_text("World.City")
    recalling = False
    try:
        title = title[0][0].lower()
    except Exception as e:
        print(f"Reading Error - {e}")
    if title != "city":
        recalibrate()
        tap_on_text("Home.World", sleep=2)
    
    time = req_text("World.FirstMarchTime", read_kind="value")
    try:
        time = time[0][0].split(':')
        time = [int(t) for t in time]
        time = time[0]*3600 + time[1]*60 + time[2]
    except Exception as e:
        print(f"Couldn't read the time properly - {e}")
    
    if not isinstance(time, int) or time < lowest_time:
        found = tap_on_template("World.Recall", sleep=1, threshold=0.9)
        recalling = True
        while found:
            tap_on_text("World.Recall.Confirm", sleep=1)
            found = tap_on_template("World.Recall",sleep=1, threshold=0.9)
    
    return recalling


def wait_till_return(lowest_time=14400):
    while(True):
        return_times = req_text(
                [
                "World.FirstMarchTime",
                "World.SecondMarchTime",
                "World.ThirdMarchTime", 
                "World.FourthMarchTime", 
                "World.FifthMarchTime"
            ],
            read_kind="value"
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

        if len(times) <= 2:
            break
        waiting_time = max(times) if len(times)>0 else 0
        if waiting_time > 600:
            recalling = recall_current_march(lowest_time=lowest_time)
        elif waiting_time == 0:
            break
        print(f"Waiting for {waiting_time} seconds for the troops to return home...")
        time.sleep(waiting_time)



def beast_intel():
    status = True
    while status:
        status = tap_on_templates_batch(
            [
                "World.Intel.Beast.Gold.2",
                "World.Intel.Beast.Purple.2",
                "World.Intel.Beast.Blue.2",
            ],
            thresholds = [0.9]*9,
            sleep = 1,
            parallel = parallel
        )
        if status:
            tap_screen(79.63, 70.73)

            found = tap_on_text("World.Intel.Beast.View", wait=1, sleep=1)
            if not found:
                continue
            try:
                data = req_text('World.MarchQueue', read_kind="value")[0][0].split('/')
                remaining_march = int(data[1]) - int(data[0])
            except Exception as e:
                print(f"Reading Error - {e}")
                remaining_march = None

            if remaining_march == 0:
                wait_till_return()
            tap_on_text("World.Intel.Beast.View.Attack", sleep=1)
            tap_on_text("World.Deploy.Equalize", sleep=1)
            tap_on_text("World.Deploy.Deploy", sleep=1)
            found = tap_on_text("Home.ChiefStamina.ObtainMore.Claim", sleep=1)
            if found:
                tap_on_template("Global.Close", sleep=1)
                tap_on_text("World.Deploy.Deploy", sleep=1)
                tap_on_template("World.Intel", sleep=1)
                continue
            tap_on_template("World.Intel", sleep=1)
            


def survivor_intel():
    status = True
    while status:
        status = tap_on_templates_batch(
            [
                "World.Intel.Survivor.Gold.2",
                "World.Intel.Survivor.Purple.2",
                "World.Intel.Survivor.Blue.2"
            ],
            thresholds = [0.9]*9,
            sleep = 1,
            parallel = parallel
        )
        if status:
            tap_screen(79.63, 70.73)
            found = tap_on_text("World.Intel.Survivor.View", wait=1, sleep=1)
            if not found:
                continue
            tap_on_text("World.Intel.Survivor.View.Rescue", sleep=1)
            found = tap_on_text("Home.ChiefStamina.ObtainMore.Claim", sleep=1)
            if found:
                tap_on_template("Global.Close", sleep=1)
                tap_on_template("World.Intel", sleep=1)
                continue
            tap_on_template("World.Intel", sleep=1)


def exploration_intel():
    status = True
    while status:
        status = tap_on_templates_batch(
            [
                "World.Intel.Exploration.Gold.2",
                "World.Intel.Exploration.Purple.2",
                "World.Intel.Exploration.Blue.2"
            ],
            thresholds = [0.9]*9,
            sleep = 1,
            parallel = parallel
        )
        if status:
            tap_screen(79.63, 70.73)

            found = tap_on_text("World.Intel.Exploration.View", wait=1, sleep=1)
            if not found:
                continue
            tap_on_text("World.Intel.Exploration.View.Explore", sleep=1)
            found = tap_on_text("Home.ChiefStamina.ObtainMore.Claim", sleep=1)
            if found:
                tap_on_template("Global.Close", sleep=1)
                tap_on_template("World.Intel", sleep=1)
                continue
            tap_on_text("Home.Exploration.Explore.QuickDeploy")
            tap_on_text("Home.Exploration.Explore.Fight", sleep=1)
            tap_on_text("Tap anywhere to exit", wait=30, sleep=1)
            tap_on_template("World.Intel", sleep=1)

    print("Finished the task Intel Mission, Returning...")
    return True

    


def intel():
    parallel = True
    print("Starting the task Intel Mission")

    title = req_text("World.City")
    recalling = False
    try:
        title = title[0][0].lower()
    except Exception as e:
        print(f"Reading Error - {e}")
    if title != "city":
        recalibrate()
        tap_on_text("Home.World", sleep=2)
    
    status = tap_on_template("World.Intel", sleep=1)

    if not status:
        print("Intel icon not found, Exiting the task...")
        return None

    #Activating Agnes skill
    tap_on_template("World.Intel.Agnes", sleep=1)

    status = tap_on_templates_batch(
        [
            "World.Intel.Survivor.Gold.2",
            "World.Intel.Survivor.Purple.2",
            "World.Intel.Survivor.Blue.2",
            "World.Intel.Beast.Gold.2",
            "World.Intel.Beast.Purple.2",
            "World.Intel.Beast.Blue.2",
            "World.Intel.Exploration.Gold.2",
            "World.Intel.Exploration.Purple.2",
            "World.Intel.Exploration.Blue.2"
        ],
        tap = False,
        parallel = parallel
    )
    if status:
        tap_on_template("Global.Back", sleep=1)
        recall_current_march(lowest_time=999999)
        wait_till_return(lowest_time=999999)
        tap_on_template("World.Intel", sleep=1)
    else:
        print("No intel found, Exiting the task...")
        return None

    survivor_intel()
    beast_intel()
    exploration_intel()

    found = tap_on_text("World.Intel.ClaimAll", sleep=1)
    if found:
        tap_on_text("Tap anywhere to exit", sleep=1)
    
    print("Intel Task finished, returning...")
    return True