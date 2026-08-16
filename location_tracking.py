import time
from gpiozero import InputDevice
from motor_module import reverse_direction, stop_motor, start_motor
from states import motor_state

DIRECTION_TIMEOUT_S = 120.0   # fail-safe: force a reversal if the inductor
                              # hasn't triggered one in this long (missed
                              # pass -- bounce, misalignment, etc.)
IGNORE_AFTER_FAILSAFE_S = 5.0  # after a forced reversal, ignore inductor
                                # edges for this long so the motor has time
                                # to physically clear the sensor before we
                                # start listening to it again -- otherwise
                                # the forced reversal could just immediately
                                # re-trigger right back where it started

def track():
    """Stress-test loop: reverse the motor every time the inductor probe
    reads low, ignoring the analog signal-peak reversal used previously
    (see legacy/location_tracking.py for that logic).

    Fail-safe: if DIRECTION_TIMEOUT_S passes with no reversal at all (the
    inductor pass was missed), force one anyway and suppress the inductor
    for IGNORE_AFTER_FAILSAFE_S afterward.
    """
    inductor = InputDevice(5)
    was_low = False
    last_reversal = time.monotonic()
    ignore_inductor_until = 0.0

    try:
        while True:
            now = time.monotonic()
            is_low = not inductor.is_active
            rising_edge = is_low and not was_low
            was_low = is_low

            if rising_edge and now >= ignore_inductor_until:
                stop_motor()
                time.sleep(3)
                reverse_direction()
                start_motor(motor_state)
                last_reversal = time.monotonic()

            elif now - last_reversal >= DIRECTION_TIMEOUT_S:
                print(f"[track] No direction reversal in {DIRECTION_TIMEOUT_S:.0f}s "
                      "-- forcing one (fail-safe).")
                stop_motor()
                time.sleep(3)
                reverse_direction()
                start_motor(motor_state)
                last_reversal = time.monotonic()
                ignore_inductor_until = last_reversal + IGNORE_AFTER_FAILSAFE_S

            time.sleep(0.05)

    finally:
        inductor.close()
