#!/usr/bin/env python3
"""
Dual-electrometer live monitor.
ADS1115 + INA159 front end, two channels, one window.

Both sensors share /dev/i2c-1 (GPIO 2/3, onboard 1.8k pull-ups) at distinct
addresses -- Faraday Ring's ADDR pin was rewired off GND (-> VDD, 0x49) so
it no longer collides with the Cup's 0x48. Each sensor still gets its own
worker thread and its own SMBus handle.

On close, the full run (not just the on-screen window) is written to a
timestamped PNG next to this script.
"""

import time
import threading
from datetime import datetime
from collections import deque

import matplotlib.pyplot as plt
import matplotlib.animation as animation
from smbus2 import SMBus

# --- ADS1115 registers -------------------------------------------------------
REG_CONVERSION = 0x00
REG_CONFIG     = 0x01

# 0xC2 = OS=1, MUX=100 (AIN0 single-ended), PGA=001 (+/-4.096 V), MODE=0 (continuous)
# 0xE3 = DR=111 (860 SPS), comparator disabled
CONFIG_VAL  = [0xC2, 0xE3]
ADS1115_LSB = 4.096 / 32768.0          # 125 uV per count on the +/-4.096 V range

# --- Acquisition / display ---------------------------------------------------
HISTORY_SECONDS = 5                    # width of the live scrolling window
SAMPLE_RATE_HZ  = 100
INTERVAL_S      = 1.0 / SAMPLE_RATE_HZ
MAX_POINTS      = HISTORY_SECONDS * SAMPLE_RATE_HZ
Y_PAD_FRAC      = 0.1                  # headroom added above/below visible data
Y_LIMITS_INIT   = (-7.0, 7.0)          # only used before any data has arrived

# --- The two electrometers ---------------------------------------------------
# ADDR strapping: GND -> 0x48, VDD -> 0x49, SDA -> 0x4A, SCL -> 0x4B
SENSORS = [
    {"label": "Faraday Cup",  "bus": 1, "addr": 0x48, "color": "teal"},
    {"label": "Faraday Ring", "bus": 1, "addr": 0x49, "color": "darkorange"},
]

for s in SENSORS:
    s["x"] = deque(maxlen=MAX_POINTS)  # rolling window (last HISTORY_SECONDS)
    s["y"] = deque(maxlen=MAX_POINTS)

stop_event = threading.Event()
T0 = None                              # shared time origin for both channels


# --- Hardware ----------------------------------------------------------------
def init_adc(bus, addr):
    bus.write_i2c_block_data(addr, REG_CONFIG, CONFIG_VAL)
    time.sleep(0.1)


def read_real_voltage(bus, addr, retries=3):
    for attempt in range(retries):
        try:
            data = bus.read_i2c_block_data(addr, REG_CONVERSION, 2)
            raw_counts = (data[0] << 8) | data[1]
            if raw_counts > 32767:
                raw_counts -= 65536
            return 5.0 * (raw_counts * ADS1115_LSB - 1.25)
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(0.001)

def adc_worker(sensor):
    label = sensor["label"]
    print(f"[{label}] starting acquisition on /dev/i2c-{sensor['bus']} @ 0x{sensor['addr']:02X}")
    try:
        with SMBus(sensor["bus"]) as bus:
            init_adc(bus, sensor["addr"])
            next_sample_time = time.perf_counter()
            while not stop_event.is_set():
                voltage = read_real_voltage(bus, sensor["addr"])
                t = time.perf_counter() - T0
                sensor["x"].append(t)
                sensor["y"].append(voltage)

                next_sample_time += INTERVAL_S
                sleep_duration = next_sample_time - time.perf_counter()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                else:
                    next_sample_time = time.perf_counter()   # fell behind -- resync
    except Exception as e:
        print(f"\n[{label}] hardware error: {e}")
        stop_event.set()


# --- Live plot setup ---------------------------------------------------------
fig, axes = plt.subplots(len(SENSORS), 1, sharex=True, figsize=(9, 7))
lines = []

for ax, s in zip(axes, SENSORS):
    (ln,) = ax.plot([], [], lw=1.5, color=s["color"])
    ax.set_title(s["label"], fontsize=11, loc="left")
    ax.set_ylabel("Voltage (V)", fontsize=10)
    ax.set_ylim(*Y_LIMITS_INIT)
    ax.set_xlim(0, HISTORY_SECONDS)
    ax.grid(True, linestyle="--", alpha=0.6)
    lines.append(ln)

axes[-1].set_xlabel("Time (s)", fontsize=10)
fig.suptitle("INA159 / ADS1115 Live 100 Hz Signal Monitoring", fontsize=13)
fig.tight_layout()


def init_plot():
    for ln in lines:
        ln.set_data([], [])
    return lines


def update_plot(frame):
    for ax, ln, s in zip(axes, lines, SENSORS):
        x = list(s["x"])
        y = list(s["y"])
        n = min(len(x), len(y))
        if n:
            ln.set_data(x[:n], y[:n])
            now = x[n - 1]
            # window counts up in real elapsed seconds, sliding once past HISTORY_SECONDS
            left = max(0.0, now - HISTORY_SECONDS)
            ax.set_xlim(left, max(HISTORY_SECONDS, now + 0.2))

            # autoscale y to whatever's actually in the visible window, so
            # readings above/below a fixed guess never get clipped
            visible_y = [yi for xi, yi in zip(x[:n], y[:n]) if xi >= left]
            if visible_y:
                y_min, y_max = min(visible_y), max(visible_y)
                span = y_max - y_min
                pad = span * Y_PAD_FRAC if span > 0 else 0.5
                ax.set_ylim(y_min - pad, y_max + pad)
    return lines


# --- Save the full run on exit ----------------------------------------------
def save_run_png():
    # Snapshot the deques -- this is the last HISTORY_SECONDS on screen at close.
    snaps = [(list(s["x"]), list(s["y"]), s) for s in SENSORS]
    if not any(x for x, _, _ in snaps):
        print("No data captured -- nothing to save.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"electrometer_run_{stamp}.png"

    fig2, axes2 = plt.subplots(len(SENSORS), 1, sharex=True, figsize=(11, 7))
    for ax, (x, y, s) in zip(axes2, snaps):
        n = min(len(x), len(y))
        ax.plot(x[:n], y[:n], lw=1.0, color=s["color"])
        ax.set_title(s["label"], fontsize=11, loc="left")
        ax.set_ylabel("Voltage (V)", fontsize=10)
        ax.grid(True, linestyle="--", alpha=0.6)
    axes2[-1].set_xlabel("Time (s)", fontsize=10)
    fig2.suptitle(f"Electrometer -- last {HISTORY_SECONDS} s  --  {stamp}", fontsize=13)
    fig2.tight_layout()
    fig2.savefig(fname, dpi=150)
    print(f"Saved last {HISTORY_SECONDS} s to {fname}")


# --- Main --------------------------------------------------------------------
if __name__ == "__main__":
    T0 = time.perf_counter()

    threads = [
        threading.Thread(target=adc_worker, args=(s,), daemon=True)
        for s in SENSORS
    ]
    for t in threads:
        t.start()

    try:
        ani = animation.FuncAnimation(
            fig,
            update_plot,
            init_func=init_plot,
            interval=33,
            blit=False,
            cache_frame_data=False,
        )
        plt.show()
    except KeyboardInterrupt:
        print("\nShutting down software...")
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=1.0)
        save_run_png()
        print("Goodbye!")