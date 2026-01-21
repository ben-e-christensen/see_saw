import tkinter as tk
from tkinter import font
import threading
import time
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- HARDWARE SAFE IMPORT ---
try:
    import board
    from adafruit_ms8607 import MS8607
except (ImportError, NotImplementedError):
    board = None
    MS8607 = None

def launch_pht_window(parent):
    """
    Launches the PHT window.
    RETURNS a dictionary of handles so the Main Controller can:
      1. Read 'latest_readings'
      2. Update the plots using 'lines' and 'canvas'
    """
    pht_win = tk.Toplevel(parent)
    pht_win.title("Environment (MS8607) - Passive Mode")
    pht_win.geometry("600x750")
    pht_win.configure(bg="#2c3e50")

    # --- SHARED STATE ---
    # The internal thread writes to this.
    # The external Main Controller reads from this.
    latest_readings = {"temp": 0.0, "pressure": 0.0, "humidity": 0.0}

    # --- UI LAYOUT ---
    top_frame = tk.Frame(pht_win, bg="#2c3e50")
    top_frame.pack(side=tk.TOP, fill="x", pady=10)

    graph_frame = tk.Frame(pht_win, bg="white")
    graph_frame.pack(side=tk.BOTTOM, fill="both", expand=True)

    header_font = font.Font(family="Helvetica", size=10, weight="bold")
    value_font = font.Font(family="Helvetica", size=16, weight="bold")

    # --- LABELS (Top) ---
    tk.Label(top_frame, text="Temp", font=header_font, bg="#2c3e50", fg="#ecf0f1").grid(row=0, column=0, padx=20)
    temp_var = tk.StringVar(value="--")
    tk.Label(top_frame, textvariable=temp_var, font=value_font, bg="#2c3e50", fg="#e74c3c").grid(row=1, column=0, padx=20)

    tk.Label(top_frame, text="Pressure", font=header_font, bg="#2c3e50", fg="#ecf0f1").grid(row=0, column=1, padx=20)
    press_var = tk.StringVar(value="--")
    tk.Label(top_frame, textvariable=press_var, font=value_font, bg="#2c3e50", fg="#3498db").grid(row=1, column=1, padx=20)

    tk.Label(top_frame, text="Humidity", font=header_font, bg="#2c3e50", fg="#ecf0f1").grid(row=0, column=2, padx=20)
    hum_var = tk.StringVar(value="--")
    tk.Label(top_frame, textvariable=hum_var, font=value_font, bg="#2c3e50", fg="#2ecc71").grid(row=1, column=2, padx=20)

    # --- PLOTS (Bottom) ---
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(5, 6), sharex=True)
    plt.subplots_adjust(hspace=0.3, bottom=0.15)

    # Temp
    line_t, = ax1.plot([], [], 'r.-', linewidth=1)
    ax1.set_ylabel("Temp (°C)")
    ax1.grid(True, linestyle='--', alpha=0.5)

    # Pressure
    line_p, = ax2.plot([], [], 'b.-', linewidth=1)
    ax2.set_ylabel("Press (hPa)")
    ax2.grid(True, linestyle='--', alpha=0.5)

    # Humidity
    line_h, = ax3.plot([], [], 'g.-', linewidth=1)
    ax3.set_ylabel("Hum (%)")
    ax3.set_xlabel("Peak Count #")
    ax3.grid(True, linestyle='--', alpha=0.5)

    canvas = FigureCanvasTkAgg(fig, master=graph_frame)
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --- SENSOR THREAD ---
    # This ONLY updates the text labels and the 'latest_readings' dict.
    # It does NOT touch the graphs (The Main Controller does that).
    def sensor_loop():
        sensor = None
        # Try connection
        if board and MS8607:
            try:
                i2c = board.I2C()
                sensor = MS8607(i2c)
            except Exception:
                pass
        
        while True:
            # Kill thread if window closes
            try:
                if not pht_win.winfo_exists(): break
            except: break

            t, p, h = 0.0, 0.0, 0.0
            
            if sensor:
                try:
                    t = sensor.temperature
                    p = sensor.pressure
                    h = sensor.relative_humidity
                except: pass
            else:
                # Simulation defaults if no hardware
                import random
                t = 25.0 + random.uniform(-0.1, 0.1)
                p = 1013.0 + random.uniform(-1, 1)
                h = 45.0 + random.uniform(-0.5, 0.5)

            # Update Shared State
            latest_readings["temp"] = t
            latest_readings["pressure"] = p
            latest_readings["humidity"] = h
            
            # Update UI Text (Thread-safe enough for Tkinter Vars)
            try:
                temp_var.set(f"{t:.1f}°C")
                press_var.set(f"{p:.1f} hPa")
                hum_var.set(f"{h:.1f}%")
            except: pass

            time.sleep(0.1)

    # Start Sensor Thread
    t = threading.Thread(target=sensor_loop, daemon=True)
    t.start()

    # --- CRITICAL: RETURN HANDLES ---
    return {
        "latest_readings": latest_readings,
        "canvas": canvas,
        "lines": [line_t, line_p, line_h],
        "axes": [ax1, ax2, ax3]
    }