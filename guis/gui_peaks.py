import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

def launch_peak_window(parent):
    """
    Builds the 'Discrete Peak Monitor' window.
    Returns a dictionary containing the UI elements needed for updates.
    """
    peak_win = tk.Toplevel(parent)
    peak_win.title("Discrete Peak Monitor")
    peak_win.geometry("900x450")

    # --- Layout Frames ---
    left_panel = ttk.Frame(peak_win)
    left_panel.pack(side=tk.LEFT, fill="both", expand=True)
    
    right_panel = ttk.Frame(peak_win, width=300)
    right_panel.pack(side=tk.RIGHT, fill="y", padx=5, pady=5)

    # --- Matplotlib Plot ---
    fig_peak, ax_peak = plt.subplots(figsize=(5, 4))
    ax_peak.set_title("DT Detected Peaks History")
    ax_peak.set_xlabel("Peak Count")
    ax_peak.set_ylabel("Voltage")
    ax_peak.grid(True, linestyle='--', alpha=0.5)
    
    # Initialize empty scatter plots
    scatter_L = ax_peak.scatter([], [], color='red', s=5, label='Left') 
    scatter_R = ax_peak.scatter([], [], color='blue', s=5, label='Right') 
    ax_peak.legend(loc="upper right")
    
    canvas_peak = FigureCanvasTkAgg(fig_peak, master=left_panel)
    canvas_peak.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --- Treeview List ---
    columns = ("#", "Time", "Value")
    tree = ttk.Treeview(right_panel, columns=columns, show="headings", height=20)
    tree.heading("#", text="#")
    tree.heading("Time", text="Time")
    tree.heading("Value", text="Voltage")
    
    # Column formatting
    tree.column("#", width=50)
    tree.column("Time", width=200)
    tree.column("Value", width=100)
    
    # Scrollbar
    scrollbar = ttk.Scrollbar(right_panel, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscroll=scrollbar.set)
    scrollbar.pack(side=tk.RIGHT, fill='y')
    tree.pack(side=tk.LEFT, fill="both", expand=True)

    # --- Return Handles ---
    # We return these so the main loop in gui_control.py can update them
    return {
        "window": peak_win,
        "canvas": canvas_peak,
        "ax": ax_peak,
        "scatter_L": scatter_L,
        "scatter_R": scatter_R,
        "tree": tree
    }