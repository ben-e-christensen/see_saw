import tkinter as tk
from tkinter import ttk
import threading
import time
import os
import csv
from datetime import datetime
from queue import Queue
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from smbus2 import SMBus
import numpy as np

# Your Logic Modules (Ensure these remain accessible in your path)
from motor_module import adjust_speed, start_motor, stop_motor
from helpers import calc_spin, update_tkinter_input_box
from states import motor_state, temperature_state
from adc import I2C_BUS, init_adc, read_real_voltage

# --- IMPORT GUI MODULES ---
# Adjusted for your directory structure: guis/
from guis.gui_pht import launch_pht_window
from guis.gui_peaks import launch_peak_window

# --- CONFIG ---
SAMPLE_INTERVAL = 0.01
BUFFER_SIZE = 1000       
MAX_PEAK_HISTORY = 10000  
TRIGGER_BELOW = -0.01
TRIGGER_ABOVE = 0.005
COOLDOWN_SAMPLES = 100
PEAK_WINDOW_HALF = 10 # Checks 10 samples left, and 10 samples right

data_queue = Queue()
data_buffer, time_buffer = [], []
stop_event = threading.Event()

# State for Signal Processing
proc_state = {
    "smooth_buffer": [],     
    "window": [],            
    "peak_count": 0,
    "L_X": [], "L_Y": [], 
    "R_X": [], "R_Y": [], 
    "cooldown_timer": 0   
}

# State for PHT History (Parallel to peaks)
pht_history = {
    "indices": [],
    "temp": [],
    "pressure": [],
    "humidity": []
}

# --- FILE SYSTEM ---
def setup_trial_folder():
    usb_drive = "/media/ben/2BDC-13B91"
    if not os.path.exists(usb_drive):
        print(f"Drive not found at {usb_drive}. Saving locally.")
        base_folder = "Trials"
    else:
        base_folder = os.path.join(usb_drive, "SeeSaw_Data")

    if not os.path.exists(base_folder):
        try: os.makedirs(base_folder)
        except PermissionError: 
            print("Permission Error creating folder.")
            return None

    trial_num = 1
    while os.path.exists(os.path.join(base_folder, f"Trial{trial_num}")):
        trial_num += 1
    
    trial_folder = os.path.join(base_folder, f"Trial{trial_num}")
    os.makedirs(trial_folder)
    
    csv_path = os.path.join(trial_folder, "data_log.csv")
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Index", "Raw_Voltage", "Smooth_Voltage", "Direction", "Degrees", "Time Since Fall", "Event_Type","Pressure", "Humidity", "Temperature"])
    
    print(f"Logging to: {csv_path}")
    return csv_path

def daq_thread():
    """Reads voltage from the ADS1115/INA159 front end (Faraday Cup, /dev/i2c-1)
    in a background thread."""
    try:
        with SMBus(I2C_BUS) as bus:
            init_adc(bus)
            while not stop_event.is_set():
                try:
                    val = read_real_voltage(bus)
                    data_queue.put(val)
                except Exception as e:
                    print(f"DAQ Read Error: {e}")
                    time.sleep(0.1)
                time.sleep(SAMPLE_INTERVAL)
    except Exception as e:
        print(f"DAQ Initialization Failed: {e}")

# --- MAIN LOOP ---
def update_plot(root, canvas_live, fig_live, ax_live, line_live, 
                peak_ui, pht_ui, csv_path):
    """
    Handles data processing and updates:
    1. Live Signal Plot (Local)
    2. Discrete Peak Plot (gui_peaks)
    3. PHT Sensor Graphs (gui_pht) - NOW SYNCHRONIZED WITH PEAK HISTORY
    """
    new_pts = 0
    peak_detected = False
    current_peak_data = None 
    csv_data = [] 
    global proc_state, pht_history
    
    while not data_queue.empty():
        raw_val = data_queue.get()
        current_dir = motor_state.get('dir', 'l') 

        # Smoothing
        proc_state["smooth_buffer"].append(raw_val)
        if len(proc_state["smooth_buffer"]) > 5:
            proc_state["smooth_buffer"].pop(0)
        smooth_val = sum(proc_state["smooth_buffer"]) / len(proc_state["smooth_buffer"])

        data_buffer.append(smooth_val)
        current_idx = len(time_buffer)
        time_buffer.append(current_idx)
        
        proc_state["window"].append(smooth_val)
        event_label = "" 
        
        if proc_state["cooldown_timer"] > 0:
            proc_state["cooldown_timer"] -= 1

# --- UPGRADED PEAK DETECTION LOGIC ---
        window_size = (PEAK_WINDOW_HALF * 2) + 1 
        
        if len(proc_state["window"]) == window_size:
            mid_val = proc_state["window"][PEAK_WINDOW_HALF]
            
            is_peak = (mid_val == max(proc_state["window"]))
            is_valley = (mid_val == min(proc_state["window"]))
            
            valid_peak = is_peak and (mid_val > TRIGGER_ABOVE)
            valid_valley = is_valley and (mid_val < TRIGGER_BELOW)

            if (valid_valley or valid_peak) and (proc_state["cooldown_timer"] == 0):
                event_label = "VALLEY" if valid_valley else "PEAK"
                proc_state["peak_count"] += 1
                
                # Update Peak Logic (Left vs Right)
                target_X, target_Y = (proc_state["L_X"], proc_state["L_Y"]) if current_dir == 'l' else (proc_state["R_X"], proc_state["R_Y"])
                target_X.append(proc_state["peak_count"])
                target_Y.append(mid_val)
                
                if len(target_X) > MAX_PEAK_HISTORY:
                    target_X.pop(0)
                    target_Y.pop(0)

                # --- PHT DATA CAPTURE (Restored) ---
                t_val, p_val, h_val = 0.0, 0.0, 0.0 
                if pht_ui: 
                    try:
                        readings = pht_ui.get('latest_readings', {})
                        t_val = readings.get('temp', 0.0)
                        p_val = readings.get('pressure', 0.0)
                        h_val = readings.get('humidity', 0.0)
                    except Exception:
                        pass 

                pht_history["indices"].append(proc_state["peak_count"])
                pht_history["temp"].append(t_val)
                pht_history["pressure"].append(p_val)
                pht_history["humidity"].append(h_val)
                
                if len(pht_history["indices"]) > MAX_PEAK_HISTORY: 
                    for key in pht_history: 
                        if pht_history[key]: 
                            pht_history[key].pop(0)

                peak_detected = True
                motor_state['peak']=True
                proc_state["cooldown_timer"] = COOLDOWN_SAMPLES 
                
                timestamp_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                current_peak_data = (proc_state["peak_count"], timestamp_log, f"{mid_val:.3f} V")
                print(f"#{proc_state['peak_count']} [{event_label}] at {mid_val:.3f} V")

            # Pop the oldest point to keep the window rolling
            proc_state["window"].pop(0)
        
        # Timestamp for CSV
        timestamp_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        csv_data.append([timestamp_log, current_idx, raw_val, smooth_val, current_dir, motor_state['deg'], motor_state['time_since_peak'], event_label, temperature_state['p'],temperature_state['h'],temperature_state['t'],])
        new_pts += 1

    # Write to CSV
    if csv_data and csv_path:
        try:
            with open(csv_path, 'a', newline='') as f:
                csv.writer(f).writerows(csv_data)
        except Exception:
            pass

    # 1. Update Live Plot (Main Window)
    if new_pts:
        if len(data_buffer) > BUFFER_SIZE:
            data_buffer[:] = data_buffer[-BUFFER_SIZE:]
            time_buffer[:] = list(range(len(data_buffer)))
        line_live.set_xdata(time_buffer)
        line_live.set_ydata(data_buffer)
        ax_live.set_xlim(0, BUFFER_SIZE)
        if data_buffer:
            ymin, ymax = min(data_buffer), max(data_buffer)
            ax_live.set_ylim(min(ymin, -0.2), max(ymax, 0.2))
        canvas_live.draw_idle()
        
    # 2. Update Peak Plot & PHT Graphs (Only if peak occurred)
    if peak_detected:
        try:
            total_count = proc_state["peak_count"]
            
            # --- Update Discrete Peak Scatter ---
            if proc_state["L_X"]: peak_ui["scatter_L"].set_offsets(np.c_[proc_state["L_X"], proc_state["L_Y"]])
            if proc_state["R_X"]: peak_ui["scatter_R"].set_offsets(np.c_[proc_state["R_X"], proc_state["R_Y"]])
            
            # Scroll Peak Window
            peak_ui["ax"].set_xlim(max(0, total_count - MAX_PEAK_HISTORY), total_count + 10) 
            all_ys = proc_state["L_Y"] + proc_state["R_Y"]
            if all_ys: peak_ui["ax"].set_ylim(min(all_ys) - 0.1, max(all_ys) + 0.1) 
            peak_ui["canvas"].draw_idle()

            if current_peak_data:
                peak_ui["tree"].insert("", 0, values=current_peak_data)

            # --- Update PHT Graphs (FIXED SCROLLING) ---
            x_vals = pht_history["indices"]
            
            # Helper to update axes
            def update_pht_ax(idx, data, label):
                pht_ui['lines'][idx].set_data(x_vals, data)
                ax = pht_ui['axes'][idx]
                
                # Match the scrolling logic of the Peak Window
                ax.set_xlim(max(0, total_count - MAX_PEAK_HISTORY), total_count + 10)
                
                # Auto-scale Y only
                ax.relim()
                ax.autoscale_view(scalex=False, scaley=True)

            update_pht_ax(0, pht_history["temp"], "Temp")
            update_pht_ax(1, pht_history["pressure"], "Pressure")
            update_pht_ax(2, pht_history["humidity"], "Humidity")
            
            pht_ui['canvas'].draw_idle()

        except Exception as e:
            print(f"Plot Update Error: {e}")

    # Schedule Next Loop
    root.after(50, lambda: update_plot(root, canvas_live, fig_live, ax_live, line_live, 
                                       peak_ui, pht_ui, csv_path))

def build_motor_controls(parent):
    frame = ttk.Frame(parent, padding=6)
    inc_val = tk.StringVar(value="0.1")
    result_label = ttk.Label(frame, text=(f"Delay: {motor_state['delay']*10e5:.0f} us\nSteps: {int(motor_state['total_steps'])}"), justify="left")
    freq_label = ttk.Label(frame, text="Frequency (RPM):")
    freq = ttk.Entry(frame, width=15)
    total_revs = 1
    update_tkinter_input_box(freq, 1)

    def handle_enter(event=None):
        calc_spin(freq.get(), total_revs, motor_state, result_label, freq, total_revs)

    buttons = [
        ("Start Motor", lambda: start_motor(motor_state)),
        ("Stop Motor", stop_motor),
        ("Speed Up", lambda: adjust_speed(motor_state, 'u', result_label, inc_val, motor_state["revs"], freq, total_revs)),
        ("Slow Down", lambda: adjust_speed(motor_state, 'd', result_label, inc_val, motor_state["revs"], freq, total_revs)),
    ]
    for text, cmd in buttons: ttk.Button(frame, text=text, command=cmd).pack(pady=2, fill="x")
    
    ttk.Label(frame, text="Increment (RPM):").pack(pady=2)
    ttk.Spinbox(frame, from_=0, to=10, increment=0.1, textvariable=inc_val, width=10).pack()
    freq_label.pack(pady=4)
    freq.pack()
    ttk.Button(frame, text="Get Input", command=handle_enter).pack(pady=4)
    result_label.pack(pady=4)
    
    frame.bind("<Return>", handle_enter)
    return frame

def run_control_gui():
    csv_path = setup_trial_folder()
    root = tk.Tk()
    root.title("Main Control & Live View")
    root.geometry("800x500")

    # 1. Launch PHT Window (Environment)
    pht_ui = launch_pht_window(root)

    # 2. Launch Peak Window (Discrete Analysis)
    peak_ui = launch_peak_window(root)

    # 3. Build Main Window Layout
    motor_frame = build_motor_controls(root)
    motor_frame.pack(side=tk.LEFT, fill="y", padx=8, pady=8)

    plot_frame_live = ttk.Frame(root)
    plot_frame_live.pack(side=tk.RIGHT, fill="both", expand=True, padx=8, pady=8)

    fig_live, ax_live = plt.subplots(figsize=(5, 4))
    fig_live.suptitle("Live Signal")
    ax_live.set_ylabel("Voltage (V)")
    ax_live.grid(True)
    line_live, = ax_live.plot([], [], 'b-', linewidth=1)
    
    canvas_live = FigureCanvasTkAgg(fig_live, master=plot_frame_live)
    canvas_live.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # 4. Start Threads and Loop
    threading.Thread(target=daq_thread, daemon=True).start()
    
    # Start the recursive update loop
    root.after(50, lambda: update_plot(root, canvas_live, fig_live, ax_live, line_live, 
                                       peak_ui, pht_ui, csv_path))

    def on_close():
        stop_event.set()
        root.destroy() 

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    run_control_gui()