from gui_module import run_gui
from location_tracking import track
import threading
from gpiozero import InputDevice

def main():
    tracking_thread = threading.Thread(target=track, daemon=True)
    tracking_thread.start()

    # Main thread → GUI (motor controls + MCC118 plot)
    run_gui()


if __name__ == '__main__':
    main()
