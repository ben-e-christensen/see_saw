from gpiozero import OutputDevice, InputDevice
from time import sleep, time
import threading
from states import motor_state
from helpers import calc_spin

# --- HARDWARE CONFIG ---
# Motor Pins
step = OutputDevice(4)
direction = OutputDevice(17)

# Sensor Pins (Inductors)
# Assuming Inductors go ACTIVE (True) when triggered. 
# If they are normally True and go False when triggered, change logic in check_sensors.
inductor_L = InputDevice(5, pull_up=True) # Adjust pull_up based on your wiring
inductor_R = InputDevice(6, pull_up=True)

stop_event = threading.Event()

# --- CONSTANTS ---
STEPS_PER_REV = 6400
BURST_ANGLE = 10  # Degrees
STEPS_PER_BURST = int(STEPS_PER_REV * (BURST_ANGLE / 360.0)) # ~178 steps
PAUSE_DURATION = 1.0 # Seconds

def check_sensors():
    """Returns 'l' if left sensor hit, 'r' if right hit, else None"""
    # Note: Adjust .is_active vs not .is_active based on your specific sensor type
    if inductor_L.is_active: return 'l'
    if inductor_R.is_active: return 'r'
    return None

def motor_control(state, run_time):
    """
    Main Thread: Moves in bursts using Dead Reckoning (Step Counting).
    """
    start_time = time()
    state['running'] = True
    
    # Ensure we have a limit from calibration
    if state.get('max_steps', 0) == 0:
        print("WARNING: Uncalibrated. Please run Calibration first.")
        state['running'] = False
        return

    print(f"Starting Burst Mode. Track Length: {state['max_steps']} steps.")
    
    # Internal counter for this session (starts at 0 or max depending on side)
    # We assume we start at 0 (Left) after calibration.
    current_pos = 0 if state['dir'] == 'r' else state['max_steps']

    while not stop_event.is_set():
        # 1. Determine Target for this specific burst
        target_direction = state['dir'] # 'l' or 'r'
        
        # Set hardware pin
        # Assuming direction.on() is Right, off() is Left (verify your wiring)
        if target_direction == 'r':
            direction.on()
            distance_to_wall = state['max_steps'] - current_pos
        else:
            direction.off()
            distance_to_wall = current_pos # Distance to 0
            
        # 2. Calculate Steps to Move (Burst vs Remaining)
        steps_to_take = min(STEPS_PER_BURST, distance_to_wall)
        
        # 3. Execute Steps
        if steps_to_take > 0:
            for _ in range(steps_to_take):
                if stop_event.is_set(): break
                step.on()
                sleep(state['delay'])
                step.off()
                sleep(state['delay'])
            
            # Update Position
            if target_direction == 'r':
                current_pos += steps_to_take
            else:
                current_pos -= steps_to_take
                
        # 4. Check if we hit the wall (End of Track)
        # We use strict equality because we use integer math
        at_right_wall = (target_direction == 'r' and current_pos >= state['max_steps'])
        at_left_wall  = (target_direction == 'l' and current_pos <= 0)

        if at_right_wall or at_left_wall:
            print(f"Wall hit at {current_pos}. Reversing...")
            reverse_direction()
            # Optional: Longer pause at the ends?
        
        # 5. Pause between bursts
        sleep(PAUSE_DURATION)

    state['running'] = False
    print("Motor stopped.")

def calibrate(state):
    """
    Blocking function to find track length.
    1. Moves Left until sensor.
    2. Moves Right until sensor, counting steps.
    3. Saves count to state['max_steps'].
    """
    stop_event.clear()
    print("--- STARTING CALIBRATION ---")
    
    # Phase 1: Go Home (Left)
    print("Seeking Left Limit...")
    direction.off() # Assume Off is Left
    
    while not inductor_L.is_active:
        if stop_event.is_set(): return
        step.on()
        sleep(state['delay'])
        step.off()
        sleep(state['delay'])
    
    print("Left Limit Found. Zeroing.")
    
    # Back off slightly to clear sensor
    direction.on()
    for _ in range(50):
        step.on()
        sleep(state['delay'])
        step.off()
        sleep(state['delay'])
        
    # Phase 2: Measure Track (Go Right)
    print("Measuring Track (Seeking Right Limit)...")
    direction.on() # Right
    total_steps = 0
    
    while not inductor_R.is_active:
        if stop_event.is_set(): return
        
        step.on()
        sleep(state['delay'])
        step.off()
        sleep(state['delay'])
        total_steps += 1
        
    print(f"Right Limit Found. Total Steps: {total_steps}")
    
    # Save to state
    state['max_steps'] = total_steps
    state['dir'] = 'l' # We are at Right wall, so next move is Left
    state['revs'] = 0 # Reset rev count
    
    # Back off slightly
    direction.off()
    for _ in range(50):
        step.on()
        sleep(state['delay'])
        step.off()
        sleep(state['delay'])

    print("--- CALIBRATION COMPLETE ---")

def reverse_direction():
    # Just flips the logic state. 
    # The motor_control loop picks this up in the next iteration.
    if motor_state['dir'] == 'l':
        motor_state['dir'] = 'r'
    elif motor_state['dir'] == 'r':
        motor_state['dir'] = 'l'

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