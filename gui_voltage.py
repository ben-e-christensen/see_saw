#!/usr/bin/env python3
import tkinter as tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import time
import numpy as np
from queue import Queue
from daqhats import mcc118

# --- CONFIG ---
CHANNEL = 0
SAMPLE_INTERVAL = 0.01  # seconds between reads (≈100 Hz)
BUFFER_SIZE = 500

# --- Globals ---
data_queue = Queue()
data_buffer = []
time_buffer = []
stop_event = threading.Event()

# --- Matplotlib setup ---
fig, ax = plt.subplots(figsize=(7, 4))
fig.suptitle(f"MCC 118 Channel {CHANNEL} Live Stream", fontsize=14)
ax.set_xlabel("Sample Index")
ax.set_ylabel("Voltage (V)")
ax.grid(True)
line, = ax.plot([], [], 'r-')

canvas = None   # will attach later
root = None


def daq_thread():
    """Background reader for MCC118 channel."""
    hat = mcc118()
    while not stop_event.is_set():
        try:
            value = hat.a_in_read(CHANNEL)
            data_queue.put(value)
        except Exception as e:
            print(f"DAQ read error: {e}")
            time.sleep(0.1)
        time.sleep(SAMPLE_INTERVAL)
    hat.a_in_scan_stop()


def update_plot():
    """Drain queue and update live plot."""
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

    root.after(50, update_plot)


def on_close():
    stop_event.set()
    root.destroy()


def run_gui():
    global root, canvas
    root = tk.Tk()
    root.title("MCC 118 Live Viewer")

    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    root.protocol("WM_DELETE_WINDOW", on_close)
    threading.Thread(target=daq_thread, daemon=True).start()
    root.after(50, update_plot)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
