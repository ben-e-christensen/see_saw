from gpiozero import OutputDevice
from time import sleep, time
import threading

from helpers import calc_spin


stop_event = threading.Event()

step = OutputDevice(2)
direction = OutputDevice(3)
direction.on()

def motor_control(state, run_time):
    start_time = time()
    state['running'] = True
    while True:
        if stop_event.is_set():
            state['running'] = False
            print("Motor stopped.")
            break
        step.on()
        sleep(state['delay'])
        step.off()
        sleep(state['delay'])
    elapsed = time() - start_time
    print("Loop duration:", elapsed, "seconds")
    
def reverse_direction():
    direction.value = not direction.value
    
def adjust_speed(state, direction, result_label, inc_val, revs, freq_tk, total_revs_tk):
    
    steps_per_rev = 6400
    steps_per_sec = 1.0 / ( 2.0 * state['delay'])
    freq = (steps_per_sec * 60.0) / steps_per_rev
    
    if(direction == 'u'):
        freq += float(inc_val.get())
    elif(direction == 'd'):
        freq -= float(inc_val.get())
    

    calc_spin(freq, revs, state, result_label, freq_tk, total_revs_tk)
    
def start_motor(state):
    stop_event.clear()
    
    print("Starting motor thread...")
    
    thread = threading.Thread(target=motor_control, args=(state, True))
    thread.start()

    

def stop_motor():
    stop_event.set()
    
    
    