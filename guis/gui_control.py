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
from adc import init_adc, read_real_voltage

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
PEAK_WINDOW_HALF = 10  # Checks 10 samples left, and 10 samples right
PEAK_PROMINENCE = 0.02  # Volts the center sample must clear both window flanks by -- filters flatlines/clipping

# --- The two electrometers (share /dev/i2c-1, distinguished by ADDR) ---
# ADDR strapping: GND -> 0x48, VDD -> 0x49, SDA -> 0x4A, SCL -> 0x4B
SENSORS = [
    {"label": "Faraday Cup",  "bus": 1, "addr": 0x48, "color": "teal"},
    {"label": "Faraday Ring", "bus": 1, "addr": 0x49, "color": "darkorange"},
]
PRIMARY_LABEL = SENSORS[0]["label"]  # drives PHT-history capture and motor_state['peak']

stop_event = threading.Event()


def make_channel_state(sensor):
    return {
        "bus": sensor["bus"],
        "color": sensor["color"],
        "queue": Queue(),
        "data_buffer": [],
        "time_buffer": [],
        "proc_state": {
            "smooth_buffer": [],
            "window": [],
            "peak_count": 0,
            "L_X": [], "L_Y": [],
            "R_X": [], "R_Y": [],
            "cooldown_timer": 0,
        },
    }


channels = {s["label"]: make_channel_state(s) for s in SENSORS}

# State for PHT History (Parallel to the primary channel's peak history)
pht_history = {
    "indices": [],
    "temp": [],
    "pressure": [],
    "humidity": []
}

# --- FILE SYSTEM ---
def setup_trial_folder():
    usb_drive = "/media/ben/Lexar"
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
        writer.writerow(["Timestamp", "Index", "Channel", "Raw_Voltage", "Smooth_Voltage", "Direction", "Degrees", "Time Since Fall", "Event_Type", "Pressure", "Humidity", "Temperature"])

    print(f"Logging to: {csv_path}")
    return csv_path

RECONNECT_BACKOFF_S = 1.0
MAX_RECONNECT_BACKOFF_S = 30.0
FALLBACK_REINIT_INTERVAL_S = 300.0  # coarse safety net only -- covers the
                                    # case where the motor somehow runs
                                    # uninterrupted this long without ever
                                    # stopping at the inductor sensor


def daq_thread(sensor):
    """Reads voltage from one sensor's ADS1115/INA159 front end in a
    background thread. Both sensors share bus 1, distinguished by addr.

    Meant to run unattended for weeks, so any failure is treated as
    recoverable rather than fatal: a raised I2C error (NACK, bus lockup,
    etc.) closes and reopens the bus with backoff. The config register is
    also re-sent every time the motor stops (motor_state['running'] goes
    True -> False at the inductor sensor) -- no usable charge data is
    expected during that window anyway, so it's a free opportunity to
    correct a silent ADC reset (one where reads keep "succeeding" but just
    return a stale/frozen value, since nothing raises to trigger a
    reconnect on its own). FALLBACK_REINIT_INTERVAL_S is just a backstop
    in case the motor is ever run continuously for longer than that."""
    label = sensor["label"]
    addr = sensor["addr"]
    ch = channels[label]
    backoff = RECONNECT_BACKOFF_S

    while not stop_event.is_set():
        try:
            with SMBus(sensor["bus"]) as bus:
                init_adc(bus, addr)
                backoff = RECONNECT_BACKOFF_S  # reset once a connection sticks
                last_init = time.monotonic()
                was_running = motor_state.get('running', False)
                while not stop_event.is_set():
                    now = time.monotonic()
                    is_running = motor_state.get('running', False)
                    motor_just_stopped = was_running and not is_running
                    was_running = is_running

                    if motor_just_stopped or (now - last_init >= FALLBACK_REINIT_INTERVAL_S):
                        init_adc(bus, addr)
                        last_init = now

                    val = read_real_voltage(bus, addr)
                    ch["queue"].put(val)
                    time.sleep(SAMPLE_INTERVAL)
        except Exception as e:
            if not stop_event.is_set():
                print(f"[{label}] DAQ error, reconnecting in {backoff:.0f}s: {e}")
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_RECONNECT_BACKOFF_S)


def _detect_event(window, half):
    """Prominence-based peak/valley test: the center sample must clear BOTH
    window flanks by PEAK_PROMINENCE, not just tie the window max/min. A flat
    or clipped stretch has near-zero flank difference and no longer qualifies
    -- fixes the old detector re-firing on flatlines every cooldown period."""
    mid_val = window[half]
    left, right = window[:half], window[half + 1:]
    is_peak = (mid_val == max(window)
               and (mid_val - max(left)) >= PEAK_PROMINENCE
               and (mid_val - max(right)) >= PEAK_PROMINENCE)
    is_valley = (mid_val == min(window)
                 and (min(left) - mid_val) >= PEAK_PROMINENCE
                 and (min(right) - mid_val) >= PEAK_PROMINENCE)
    return is_peak, is_valley, mid_val


def process_channel_sample(label, ch, raw_val, current_dir, pht_ui, is_primary):
    """Smoothing + peak detection for one channel's one new sample. Same
    logic runs independently for every channel via its own proc_state."""
    proc_state = ch["proc_state"]

    proc_state["smooth_buffer"].append(raw_val)
    if len(proc_state["smooth_buffer"]) > 5:
        proc_state["smooth_buffer"].pop(0)
    smooth_val = sum(proc_state["smooth_buffer"]) / len(proc_state["smooth_buffer"])

    proc_state["window"].append(smooth_val)
    event_label = ""
    peak_detected = False
    current_peak_data = None

    if proc_state["cooldown_timer"] > 0:
        proc_state["cooldown_timer"] -= 1

    window_size = (PEAK_WINDOW_HALF * 2) + 1

    if len(proc_state["window"]) == window_size:
        is_peak, is_valley, mid_val = _detect_event(proc_state["window"], PEAK_WINDOW_HALF)

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

            if is_primary:
                # --- PHT DATA CAPTURE (only the primary/Cup channel drives this) ---
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

                motor_state['peak'] = True

            peak_detected = True
            proc_state["cooldown_timer"] = COOLDOWN_SAMPLES

            timestamp_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            current_peak_data = (proc_state["peak_count"], timestamp_log, f"{mid_val:.3f} V")
            print(f"[{label}] #{proc_state['peak_count']} [{event_label}] at {mid_val:.3f} V")

        # Pop the oldest point to keep the window rolling
        proc_state["window"].pop(0)

    return smooth_val, event_label, peak_detected, current_peak_data


# --- MAIN LOOP ---
def update_plot(root, canvas_live, fig_live, axes_live, lines_live,
                peak_uis, pht_ui, csv_path):
    """
    Handles data processing and updates, per channel:
    1. Live Signal Plot (Local)
    2. Discrete Peak Plot (gui_peaks) -- one window per channel
    3. PHT Sensor Graphs (gui_pht) -- synchronized with the primary channel's peak history
    """
    csv_data = []
    peaks_by_channel = {}
    any_new_pts = False

    for s in SENSORS:
        label = s["label"]
        ch = channels[label]
        is_primary = (label == PRIMARY_LABEL)
        new_pts = 0
        current_peak_data = None

        while not ch["queue"].empty():
            raw_val = ch["queue"].get()
            current_dir = motor_state.get('dir', 'l')

            smooth_val, event_label, peak_detected, peak_data = process_channel_sample(
                label, ch, raw_val, current_dir, pht_ui, is_primary
            )

            ch["data_buffer"].append(smooth_val)
            current_idx = len(ch["time_buffer"])
            ch["time_buffer"].append(current_idx)

            if peak_detected:
                current_peak_data = peak_data

            timestamp_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            csv_data.append([timestamp_log, current_idx, label, raw_val, smooth_val, current_dir,
                              motor_state['deg'], motor_state['time_since_peak'], event_label,
                              temperature_state['p'], temperature_state['h'], temperature_state['t']])
            new_pts += 1

        # 1. Update Live Plot for this channel
        if new_pts:
            any_new_pts = True
            if len(ch["data_buffer"]) > BUFFER_SIZE:
                ch["data_buffer"][:] = ch["data_buffer"][-BUFFER_SIZE:]
                ch["time_buffer"][:] = list(range(len(ch["data_buffer"])))
            lines_live[label].set_xdata(ch["time_buffer"])
            lines_live[label].set_ydata(ch["data_buffer"])
            ax = axes_live[label]
            ax.set_xlim(0, BUFFER_SIZE)
            if ch["data_buffer"]:
                ymin, ymax = min(ch["data_buffer"]), max(ch["data_buffer"])
                ax.set_ylim(min(ymin, -0.2), max(ymax, 0.2))

        if current_peak_data:
            peaks_by_channel[label] = current_peak_data

    if any_new_pts:
        canvas_live.draw_idle()

    # Write to CSV
    if csv_data and csv_path:
        try:
            with open(csv_path, 'a', newline='') as f:
                csv.writer(f).writerows(csv_data)
        except Exception:
            pass

    # 2. Update each channel's Peak Plot
    for label, current_peak_data in peaks_by_channel.items():
        try:
            proc_state = channels[label]["proc_state"]
            peak_ui = peak_uis[label]
            total_count = proc_state["peak_count"]

            if proc_state["L_X"]: peak_ui["scatter_L"].set_offsets(np.c_[proc_state["L_X"], proc_state["L_Y"]])
            if proc_state["R_X"]: peak_ui["scatter_R"].set_offsets(np.c_[proc_state["R_X"], proc_state["R_Y"]])

            peak_ui["ax"].set_xlim(max(0, total_count - MAX_PEAK_HISTORY), total_count + 10)
            all_ys = proc_state["L_Y"] + proc_state["R_Y"]
            if all_ys: peak_ui["ax"].set_ylim(min(all_ys) - 0.1, max(all_ys) + 0.1)
            peak_ui["canvas"].draw_idle()

            peak_ui["tree"].insert("", 0, values=current_peak_data)
        except Exception as e:
            print(f"[{label}] Plot Update Error: {e}")

    # 3. Update PHT Graphs -- only advances when the primary channel logs a peak
    if PRIMARY_LABEL in peaks_by_channel:
        try:
            total_count = channels[PRIMARY_LABEL]["proc_state"]["peak_count"]
            x_vals = pht_history["indices"]

            def update_pht_ax(idx, data):
                pht_ui['lines'][idx].set_data(x_vals, data)
                ax = pht_ui['axes'][idx]
                ax.set_xlim(max(0, total_count - MAX_PEAK_HISTORY), total_count + 10)
                ax.relim()
                ax.autoscale_view(scalex=False, scaley=True)

            update_pht_ax(0, pht_history["temp"])
            update_pht_ax(1, pht_history["pressure"])
            update_pht_ax(2, pht_history["humidity"])

            pht_ui['canvas'].draw_idle()
        except Exception as e:
            print(f"PHT Plot Update Error: {e}")

    # Schedule Next Loop
    root.after(50, lambda: update_plot(root, canvas_live, fig_live, axes_live, lines_live,
                                       peak_uis, pht_ui, csv_path))

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

    # 2. Launch a Discrete Peak Monitor window per channel
    peak_uis = {
        s["label"]: launch_peak_window(root, title=f"Discrete Peak Monitor — {s['label']}")
        for s in SENSORS
    }

    # 3. Build Main Window Layout
    motor_frame = build_motor_controls(root)
    motor_frame.pack(side=tk.LEFT, fill="y", padx=8, pady=8)

    plot_frame_live = ttk.Frame(root)
    plot_frame_live.pack(side=tk.RIGHT, fill="both", expand=True, padx=8, pady=8)

    # Two stacked live plots, one per channel -- mirrors fly.py's layout
    fig_live, axes_live_list = plt.subplots(len(SENSORS), 1, sharex=True, figsize=(5, 6))
    fig_live.suptitle("Live Signal")

    axes_live = {}
    lines_live = {}
    for ax, s in zip(axes_live_list, SENSORS):
        ax.set_title(s["label"], fontsize=10, loc="left")
        ax.set_ylabel("Voltage (V)")
        ax.grid(True)
        (line,) = ax.plot([], [], color=s["color"], linewidth=1)
        axes_live[s["label"]] = ax
        lines_live[s["label"]] = line
    axes_live_list[-1].set_xlabel("Sample Index")
    fig_live.tight_layout()

    canvas_live = FigureCanvasTkAgg(fig_live, master=plot_frame_live)
    canvas_live.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # 4. Start Threads and Loop
    for s in SENSORS:
        threading.Thread(target=daq_thread, args=(s,), daemon=True).start()

    # Start the recursive update loop
    root.after(50, lambda: update_plot(root, canvas_live, fig_live, axes_live, lines_live,
                                       peak_uis, pht_ui, csv_path))

    def on_close():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    run_control_gui()
