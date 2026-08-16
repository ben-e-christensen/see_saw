import time
import threading
from collections import deque
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from smbus2 import SMBus

# --- Hardware Configuration ---
I2C_BUS = 1
ADC_ADDR = 0x48   # kept as the default for this module's own __main__ demo below

REG_CONVERSION = 0x00
REG_CONFIG = 0x01

# Config register bitmask setup:
# Bits 15-8: 0xC2 (AIN0 single-ended, ±4.096V range, Continuous Mode)
# Bits 7-0:  0xA3 (Upgraded to 250 SPS data rate, comparator disabled)
CONFIG_VAL = [0xC2, 0xE3]
ADS1115_LSB = 0.000125  

# --- Live Plotting Parameters ---
HISTORY_SECONDS = 5            # How many seconds of data to display on screen
SAMPLE_RATE_HZ = 100           # Target polling frequency
INTERVAL_S = 1.0 / SAMPLE_RATE_HZ
MAX_POINTS = HISTORY_SECONDS * SAMPLE_RATE_HZ

# Thread-safe rolling buffers for data
data_x = deque(maxlen=MAX_POINTS)
data_y = deque(maxlen=MAX_POINTS)

stop_event = threading.Event()

def init_adc(bus, addr=ADC_ADDR):
    bus.write_i2c_block_data(addr, REG_CONFIG, CONFIG_VAL)
    time.sleep(0.1)

def read_real_voltage(bus, addr=ADC_ADDR):
    data = bus.read_i2c_block_data(addr, REG_CONVERSION, 2)
    raw_counts = (data[0] << 8) | data[1]
    
    if raw_counts > 32767:
        raw_counts -= 65536
        
    v_adc = raw_counts * ADS1115_LSB
    v_in = 5.0 * (v_adc - 1.25)  # Reversing the INA159 shift
    return v_in

# --- Background Thread for 100Hz Sampling ---
def adc_worker():
    print("Starting 100Hz background acquisition thread...")
    try:
        with SMBus(I2C_BUS) as bus:
            init_adc(bus)
            start_time = time.perf_counter()
            next_sample_time = start_time
            
            while not stop_event.is_set():
                # Read ADC and map time
                voltage = read_real_voltage(bus)
                elapsed_time = time.perf_counter() - start_time
                
                data_x.append(elapsed_time)
                data_y.append(voltage)
                
                # High-precision time tracking to prevent drift
                next_sample_time += INTERVAL_S
                sleep_duration = next_sample_time - time.perf_counter()
                if sleep_duration > 0:
                    time.sleep(sleep_duration)
                    
    except Exception as e:
        print(f"\nHardware Error in worker thread: {e}")
        stop_event.set()

# --- Main Thread Runtime Execution ---
# Figure/animation setup lives here (not at module scope) so other modules
# (e.g. guis/gui_control.py) can import init_adc()/read_real_voltage() from
# this file without popping up a plot window as a side effect.
if __name__ == "__main__":
    # --- Matplotlib Live UI Setup ---
    fig, ax = plt.subplots()
    line, = ax.plot([], [], lw=1.5, color='teal')

    ax.set_title("INA159 / ADS1115 Live 100Hz Signal Monitoring", fontsize=12)
    ax.set_xlabel("Time (Seconds)", fontsize=10)
    ax.set_ylabel("Actual Input Voltage (V)", fontsize=10)
    ax.grid(True, linestyle='--', alpha=0.6)

    # Lock the Y-axis range to prevent constant, laggy resizing
    # (Adjust these bounds to fit your expected physical input signal)
    ax.set_ylim(-7.0, 7.0)

    def init_plot():
        line.set_data([], [])
        return line,

    def update_plot(frame):
        # Snapshot the deques to local lists to prevent thread conflicts during drawing
        x = list(data_x)
        y = list(data_y)

        if x:
            line.set_data(x, y)
            # Dynamically slide the window along the X axis
            current_time = x[-1]
            ax.set_xlim(max(0, current_time - HISTORY_SECONDS), current_time + 0.2)

        return line,

    # Start the data collection thread
    worker_thread = threading.Thread(target=adc_worker, daemon=True)
    worker_thread.start()

    # Launch Matplotlib animation loop (updates visually at ~30Hz/33ms intervals)
    try:
        ani = animation.FuncAnimation(
            fig,
            update_plot,
            init_func=init_plot,
            interval=33,
            blit=True
        )
        plt.show()
    except KeyboardInterrupt:
        print("\nShutting down software...")
    finally:
        stop_event.set()
        worker_thread.join()
        print("Goodbye!")