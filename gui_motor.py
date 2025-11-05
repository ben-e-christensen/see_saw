import tkinter as tk
from motor_module import adjust_speed, reverse_direction, start_motor, stop_motor
from helpers import calc_spin, update_tkinter_input_box
from states import motor_state


def handle_enter(event=None):
    calc_spin(freq.get(), total_revs.get(), motor_state, result_label, freq, total_revs)


root = tk.Tk()
root.title("Motor Control & Angle Tracker")
root.lift()
root.attributes('-topmost', True)
root.after(100, lambda: root.attributes('-topmost', False))


# GUI state vars
inc_val = tk.StringVar(value="0.1")
checkbox_val = tk.IntVar()

result_label = tk.Label(
    root,
    text=f"Delay (us): {motor_state['delay'] * 10e5:.0f} u_sec\n"
         f"Steps: {int(motor_state['total_steps'])}\n"
         f"Total Time: {motor_state['delay'] * 2 * motor_state['total_steps']:.1f} sec"
)

start_button = tk.Button(root, text="Start Motor", command=lambda: start_motor(motor_state))
stop_button = tk.Button(root, text="Stop Motor", command=stop_motor)
reverse_button = tk.Button(root, text="Reverse", command=reverse_direction)
speed_up_button = tk.Button(
    root,
    text="Speed Up",
    command=lambda: adjust_speed(motor_state, 'u', result_label, inc_val, motor_state['revs'], freq, total_revs)
)
slow_down_button = tk.Button(
    root,
    text="Slow Down",
    command=lambda: adjust_speed(motor_state, 'd', result_label, inc_val, motor_state['revs'], freq, total_revs)
)

inc_label = tk.Label(root, text="Incremental value for speed adjustments (in revs per minute)")
inc = tk.Spinbox(root, from_=0, to=10, increment=0.1, textvariable=inc_val)

freq_label = tk.Label(root, text="Enter frequency (in revolutions per minute):")
freq = tk.Entry(root, width=30)
revs_label = tk.Label(root, text="Enter total revolutions:")
total_revs = tk.Entry(root, width=30)

update_tkinter_input_box(freq, 30)
update_tkinter_input_box(total_revs, motor_state['revs'])

checkbox = tk.Checkbutton(root, text="Run motor until stopped", variable=checkbox_val, onvalue=1, offvalue=0)
input_button = tk.Button(root, text="Get Input", command=handle_enter)

""" 
# Pack them
angle_label.pack(pady=5)
voltage_label.pack(pady=5)
video_label.pack(pady=5)
"""

for w in [
    start_button, stop_button, reverse_button, speed_up_button, slow_down_button,
    inc_label, inc, freq_label, freq, revs_label, total_revs,
    checkbox, input_button, result_label
]:
    w.pack(pady=5)

root.bind("<Return>", handle_enter)
root.bind("<KP_Enter>", handle_enter)


def run_gui():
    print('running run_gui')
    root.mainloop()
