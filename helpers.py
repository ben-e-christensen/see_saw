#helpers.py
import tkinter as tk

def calc_spin(freq, revs, state, result_label, freq_tk, total_revs_tk):
    steps_per_rev = state['spr']
    steps_per_sec = float(freq) / 60 * steps_per_rev
    delay_seconds = 1.0 / (steps_per_sec * 2.0)
    steps = float(revs) * steps_per_rev
    state['delay'] = delay_seconds
    state['total_steps'] = int(steps)
    
    update_ui(state, result_label)
    update_tkinter_input_box(freq_tk, freq)

    
def update_ui(state, result_label):
    result_label.config(text=f"Delay (us): {state['delay'] * 10e5:.0f} u_sec\nSteps: {state['total_steps']}\nTotal Time: {state['delay'] * 2 * state['total_steps']:.1f} sec")
    
def update_tkinter_input_box(input_box, val):
    input_box.delete(0, tk.END)
    if isinstance(val, float):
        val = round(val,3)
    input_box.insert(0, val)
