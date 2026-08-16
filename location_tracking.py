import time
from gpiozero import InputDevice
from motor_module import reverse_direction, stop_motor, start_motor
from states import motor_state

def track():
    """Stress-test loop: reverse the motor every time the inductor probe
    reads low, ignoring the analog signal-peak reversal used previously
    (see legacy/location_tracking.py for that logic).
    """
    inductor = InputDevice(5)
    was_low = False

    try:
        while True:
            is_low = not inductor.is_active

            if is_low and not was_low:
                stop_motor()
                time.sleep(3)
                reverse_direction()
                start_motor(motor_state)

            was_low = is_low
            time.sleep(0.05)

    finally:
        inductor.close()
