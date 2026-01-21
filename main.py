import threading
from guis.gui_control import run_control_gui 
from location_tracking import track

def main():
    # 1. Start Location Tracking (Background)
    tracking_thread = threading.Thread(target=track, daemon=True)
    tracking_thread.start()

    # 2. Launch Main GUI Application
    run_control_gui()

if __name__ == '__main__':
    main()