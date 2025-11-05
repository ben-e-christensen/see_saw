import time
from gpiozero import InputDevice
from motor_module import reverse_direction

def track():
    inductor1 = InputDevice(5)
    inductor2 = InputDevice(6)
    flag = False
    try:
        while True:
            if not flag:
                if not inductor1.is_active or not inductor2.is_active:
                    reverse_direction()
                    flag = True
                    time.sleep(0.5)
            elif flag:  # only check this when the first branch doesn't run
                if inductor1.is_active or inductor2.is_active:
                    flag = False

            time.sleep(0.05)


    
    finally:
        inductor1.close()
        inductor2.close()
