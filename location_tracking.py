import time
from gpiozero import InputDevice
from motor_module import reverse_direction, stop_motor, start_motor
from states import motor_state

def track():
    inductor = InputDevice(5)
    flag = False
    last_peak_time = None
    
    motor_state['time_since_peak'] = 0.0 

    try:
        while True:
            if last_peak_time is not None:
                motor_state['time_since_peak'] = time.time() - last_peak_time

            if motor_state.get('peak'):
                print('inside if')
                last_peak_time = time.time()
                motor_state['time_since_peak'] = 0.0
                    
                start_motor(motor_state)
                reverse_direction()
                flag = True
                motor_state['peak'] = False
                time.sleep(0.5)
            if not flag:
                if not inductor.is_active:
                    stop_motor()
                    flag = True
                    time.sleep(0.5)
            elif flag:  
                if inductor.is_active: 
                    flag = False

            time.sleep(0.05)
    
    finally:
        inductor.close()
