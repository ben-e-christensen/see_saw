#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk
import threading
import time
from queue import Queue
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from daqhats import mcc118

# your modules
from motor_module import adjust_speed, start_motor, stop_motor
from helpers import calc_spin, update_tkinter_input_box
from states import motor_state


# --- DAQ CONFIG ---
CHANNEL = 1
SAMPLE_INTERVAL = 0.01     # seconds between reads (≈100 Hz)
BUFFER_SIZE = 500

data_queue = Queue()
data_buffer, time_buffer = [], []
stop_event = threading.Event()


# --- DAQ THREAD ---
def daq_thread():
    hat = mcc118()  # use first detected MCC118 (address 0)
    while not stop_event.is_set():
        try:
            val = hat.a_in_read(CHANNEL)
            data_queue.put(val)
        except Exception as e:
            print(f"DAQ read error: {e}")
            time.sleep(0.1)
        time.sleep(SAMPLE_INTERVAL)
    hat.a_in_scan_stop()


# --- PLOT UPDATE ---
def update_plot(root, canvas, fig, ax, line):
    new_pts = 0
    while not data_queue.empty():
        val = data_queue.get()
        data_buffer.append(val)
        time_buffer.append(len(time_buffer))
        new_pts += 1

    if new_pts:
        if len(data_buffer) > BUFFER_SIZE:
            data_buffer[:] = data_buffer[-BUFFER_SIZE:]
            time_buffer[:] = list(range(len(data_buffer)))
        line.set_xdata(time_buffer)
        line.set_ydata(data_buffer)
        ax.set_xlim(0, BUFFER_SIZE)
        if data_buffer:
            ymin, ymax = min(data_buffer), max(data_buffer)
            ax.set_ylim(ymin - 0.1, ymax + 0.1)
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        canvas.draw_idle()

    root.after(50, lambda: update_plot(root, canvas, fig, ax, line))


# --- MOTOR CONTROL PANEL ---
def build_motor_controls(parent):
    frame = ttk.Frame(parent, padding=6)

    inc_val = tk.StringVar(value="0.1")
    checkbox_val = tk.IntVar()

    result_label = ttk.Label(
        frame,
        text=(
            f"Delay (us): {motor_state['delay']*10e5:.0f} u_sec\n"
            f"Steps: {int(motor_state['total_steps'])}\n"
        ),
        justify="left",
    )

    freq_label = ttk.Label(frame, text="Frequency (RPM):")
    freq = ttk.Entry(frame, width=15)
    total_revs = 1
    update_tkinter_input_box(freq, 1)


    def handle_enter(event=None):
        calc_spin(freq.get(), total_revs, motor_state, result_label, freq, total_revs)

    # buttons
    buttons = [
        ("Start Motor", lambda: start_motor(motor_state)),
        ("Stop Motor", stop_motor),
        ("Speed Up", lambda: adjust_speed(motor_state, 'u', result_label, inc_val, motor_state["revs"], freq, total_revs)),
        ("Slow Down", lambda: adjust_speed(motor_state, 'd', result_label, inc_val, motor_state["revs"], freq, total_revs)),
    ]

    for text, cmd in buttons:
        ttk.Button(frame, text=text, command=cmd).pack(pady=2, fill="x")

    ttk.Label(frame, text="Increment (RPM):").pack(pady=2)
    ttk.Spinbox(frame, from_=0, to=10, increment=0.1, textvariable=inc_val, width=10).pack()

    freq_label.pack(pady=4)
    freq.pack()

    ttk.Button(frame, text="Get Input", command=handle_enter).pack(pady=4)
    result_label.pack(pady=4)

    frame.bind("<Return>", handle_enter)
    frame.bind("<KP_Enter>", handle_enter)
    return frame


# --- MAIN GUI ---
def run_gui():
    root = tk.Tk()
    root.title("Motor Control + MCC 118 Live Viewer")

    # layout frames
    motor_frame = build_motor_controls(root)
    motor_frame.pack(side=tk.LEFT, fill="y", padx=8, pady=8)

    plot_frame = ttk.Frame(root)
    plot_frame.pack(side=tk.RIGHT, fill="both", expand=True, padx=8, pady=8)

    # matplotlib figure
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.suptitle(f"MCC 118 Channel {CHANNEL}", fontsize=12)
    ax.set_xlabel("Sample Index")
    ax.set_ylabel("Voltage (V)")
    ax.grid(True)
    line, = ax.plot([], [], 'r-')

    canvas = FigureCanvasTkAgg(fig, master=plot_frame)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # start background DAQ thread + plot updates
    threading.Thread(target=daq_thread, daemon=True).start()
    root.after(50, lambda: update_plot(root, canvas, fig, ax, line))

    def on_close():
        stop_event.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
