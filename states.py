from datetime import datetime, timedelta 

motor_state = {
    'delay': 0.00469,
    'spr': 6400,
    'revs': 3,
    'total_steps': 6400 * 3,
    'running': False,
    'dir': 'l',
    'calibrated': False,
    'no_of_steps': 0,
    'deg': 0.0,
    'peak': False,
    'time_since_peak': 0.0,
}

temperature_state = {
    'p': 0.0,
    'h': 0.0,
    't': 0.0,
}

experiment_state = {
    "start_time": None,      # When the user clicked Start
    "is_running": False,     # Is the timer active?
    "duration_days": 0.0,    # Target duration
    "elapsed_str": "00:00:00"
}