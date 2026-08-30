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


side_panel = [0, 28.05, 62.04, 67.07]
training_menu = [23.15, 56.91, 86.11, 73.17]


def train():

    recalibrate()

    status = tap_on_template("Global.SidePanel", wait=2, threshold=0.5)

    if not status:
        print("Side Panel Not found")
        tap_screen(0.37, 44.84)

    status = tap_on_text("Infantry", rois=[side_panel], wait=2, sleep=1)

    if not status:
        print("Error finding side panel, Exiting the task")
        return None
    
    for i in range(3):
        tap_screen(50, 48.78)
        time.sleep(0.3)
    tap_on_text("Train", rois = [training_menu], wait=2, sleep=0.5)
    title = req_text("Home.TroopTraining.Title")

    if title != "infantry":
        tap_on_text("Click anywhere", wait=2, sleep=0.5)

    status = tap_on_text("Home.TroopTraining.Train", wait=2)
    if not status:
        tap_screen(50, 48.78)
        status = tap_on_text("Home.TroopTraining.Train", wait=2)
    if not status:
        print("Infantry Training is not finished yet, Skipping Infantry...")

    tap_on_text("Home.TroopTraining.LancerCamp", wait=2, sleep=0.5)
    title = req_text("Home.TroopTraining.Title")

    if title != "lancer":
        tap_on_text("Click anywhere", wait=2, sleep=0.5)
    status = tap_on_text("Home.TroopTraining.Train", wait=2)
    if not status:
        print("Lancer Training is not finished yet, Skipping Lancer...")

    tap_on_text("Home.TroopTraining.MarksmanCamp", wait=2, sleep=0.5)
    title = req_text("Home.TroopTraining.Title")

    if title != "marksman":
        tap_on_text("Click anywhere", wait=2, sleep=0.5)
    status = tap_on_text("Home.TroopTraining.Train", wait=2)
    if not status:
        print("Marksman Training is not finished yet, Skipping Marksman...")

    return True



def train_infantry(Amount=None):

    recalibrate()

    status = tap_on_template("Global.SidePanel", wait=2, threshold=0.5)
    if not status:
        print("Side Panel Not found, Exiting The Task")
        return None

    tap_on_text("Infantry", rois=[side_panel], wait=2)
    for i in range(3):
        tap_screen(50, 48.78)
        time.sleep(0.3)
    tap_on_text("Train", rois = [training_menu], wait=3)

    tap_screen(50.93, 44.72)            # Taping at the middle of the screen to remove the tutorial hand icon
    trained = 0

    while(trained < Amount):
        time.sleep(0.5)
        training_amount = req_text("Home.TroopTraining.TrainingAmount", read_kind="value")
        try:
            training_amount = int(training_amount[0][0])
            trained += training_amount
        except Exception as e:
            print(f"Training Amount can't be read, Only training for one time - {e}")
            tap_on_text("Home.TroopTraining.Train", wait=2)
            break

        tap_on_text("Home.TroopTraining.Train", wait=2)
        status = tap_on_text("Home.TroopTraining.Speedup", wait=2)

        if status:
            status = tap_on_text("Home.TroopTraining.Speedup.QuickUse", wait=2)
        if status:
            tap_on_text("Home.TroopTraining.Speedup.QuickUse.Use", wait=2)
        


def train_lancer(Amount=None):

    recalibrate()

    status = tap_on_template("Global.SidePanel", wait=2, threshold=0.5)
    if not status:
        print("Side Panel Not found, Exiting The Task")
        return None

    tap_on_text("Lancer", rois=[side_panel], wait=2)
    for i in range(3):
        tap_screen(50, 48.78)
        time.sleep(0.3)
    tap_on_text("Train", rois = [training_menu], wait=2)
    
    tap_screen(50.93, 44.72)            # Taping at the middle of the screen to remove the tutorial hand icon
    trained = 0

    while(trained < Amount):
        time.sleep(0.5)
        training_amount = req_text("Home.TroopTraining.TrainingAmount", read_kind="value")
        try:
            training_amount = int(training_amount[0][0])
            trained += training_amount
        except Exception as e:
            print(f"Training Amount can't be read, Only training for one time - {e}")
            tap_on_text("Home.TroopTraining.Train", wait=2)
            break

        tap_on_text("Home.TroopTraining.Train", wait=2)
        status = tap_on_text("Home.TroopTraining.Speedup", wait=2)

        if status:
            status = tap_on_text("Home.TroopTraining.Speedup.QuickUse", wait=2)
        if status:
            tap_on_text("Home.TroopTraining.Speedup.QuickUse.Use", wait=2)



def train_marksman(Amount=None):
    
    recalibrate()

    status = tap_on_template("Global.SidePanel", wait=2, threshold=0.5)
    if not status:
        print("Side Panel Not found, Exiting The Task")
        return None

    tap_on_text("Marksman", rois=[side_panel], wait=2)
    for i in range(3):
        tap_screen(540, 1200)
        time.sleep(0.3)
    tap_on_text("Train", rois = [training_menu], wait=2)

    tap_screen(550, 1100)            #Taping at the middle of the screen to remove the tutorial hand icon
    traned = 0

    while(trained < Amount):
        time.sleep(0.5)
        training_amount = req_text("Home.TroopTraining.TrainingAmount", read_kind="value")
        try:
            training_amount = int(training_amount[0][0])
            trained += training_amount
        except Exception as e:
            print(f"Training Amount can't be read, Only training for one time - {e}")
            tap_on_text("Home.TroopTraining.Train", wait=2)
            break

        tap_on_text("Home.TroopTraining.Train", wait=2)
        status = tap_on_text("Home.TroopTraining.Speedup", wait=2)

        if status:
            status = tap_on_text("Home.TroopTraining.Speedup.QuickUse", wait=2)
        if status:
            tap_on_text("Home.TroopTraining.Speedup.QuickUse.Use", wait=2)


