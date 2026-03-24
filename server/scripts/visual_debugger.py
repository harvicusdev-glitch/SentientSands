import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sys
import os
import requests
import json
import threading
import time
import ctypes

# Hide the console window on startup if not running via pythonw
if os.name == 'nt' and not sys.executable.lower().endswith('pythonw.exe'):
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)

# --- PATH DEFINITIONS ---
# Calculated relative to the script's location (server/scripts/visual_debugger.py)
SCRIPT_PATH = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
KENSHI_SERVER_DIR = os.path.dirname(SCRIPT_DIR)
KENSHI_MOD_DIR = os.path.dirname(KENSHI_SERVER_DIR)
KENSHI_ROOT = os.path.dirname(os.path.dirname(KENSHI_MOD_DIR))

# Verification - Print to console for debugging
print(f"[DEBUGGER] SCRIPT_PATH: {SCRIPT_PATH}")
print(f"[DEBUGGER] KENSHI_SERVER_DIR: {KENSHI_SERVER_DIR}")


class VisualDebugger:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sentient Sands - Visual Debugger")
        self.root.geometry("1000x950")
        self.root.configure(bg="#0F0F0F")

        self.last_sync = 0
        self.running = True
        self.current_npc_faction = "Neutral"
        self.current_campaign = "Default"

        self.setup_styles()
        self.setup_ui()

        # Start polling thread
        self.poll_thread = threading.Thread(target=self.poll_server, daemon=True)
        self.poll_thread.start()

        self.log_tail_thread = threading.Thread(target=self.poll_log_file, daemon=True)
        self.log_tail_thread.start()

        self.events_tail_thread = threading.Thread(target=self.poll_events_file, daemon=True)
        self.events_tail_thread.start()

        self.load_models()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        # Base Dark Theme
        style.configure("TFrame", background="#0F0F0F")
        style.configure("TLabel", foreground="#BBBBBB", background="#0F0F0F", font=("Consolas", 9))
        style.configure("Header.TLabel", foreground="#FFFFFF", background="#1A1A1A", font=("Segoe UI", 10, "bold"))

        # Frame and Tooltip Headers
        style.configure("TLabelframe", background="#0F0F0F", borderwidth=1, relief="flat")
        style.configure("TLabelframe.Label", background="#0F0F0F", foreground="#00D2FF", font=("Segoe UI", 9, "bold"))

        # Premium Button Aesthetics
        style.configure("TButton",
                        foreground="#E0E0E0",
                        background="#262626",
                        borderwidth=0,
                        focuscolor="none",
                        font=("Segoe UI", 8, "bold"),
                        padding=(4, 2))

        style.map("TButton",
                  background=[("active", "#333333"), ("pressed", "#1A1A1A")],
                  foreground=[("active", "#FFFFFF")])

        # Color Variations
        style.configure("Danger.TButton", background="#4A1515")
        style.map("Danger.TButton", background=[("active", "#6A2525")])

        style.configure("Success.TButton", background="#154A15")
        style.map("Success.TButton", background=[("active", "#256A25")])

        style.configure("Money.TButton", foreground="#FFD700")

        # Stat highlighting
        style.configure("Stat.TLabel", foreground="#00D2FF", background="#0F0F0F", font=("Consolas", 9, "bold"))
        style.configure("Health.TLabel", foreground="#FF5555", background="#0F0F0F", font=("Consolas", 9, "bold"))
        style.configure("Money.TLabel", foreground="#FFD700", background="#0F0F0F", font=("Consolas", 9, "bold"))

        # Input Fields
        style.configure("TCombobox", fieldbackground="#1A1A1A", background="#0F0F0F", foreground="white")
        style.map("TCombobox", fieldbackground=[("readonly", "#1A1A1A")])

    def setup_ui(self):
        # Status Bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(side="bottom", fill="x", padx=5, pady=1)

        self.status_lbl = ttk.Label(status_frame, text="Debugger Initialized", font=("Consolas", 7))
        self.status_lbl.pack(side="left")

        self.campaign_lbl = ttk.Label(status_frame, text="CAMPAIGN: Default", font=("Consolas", 7, "bold"), foreground="#00D2FF")
        self.campaign_lbl.pack(side="right")

        # Notebook tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=4, pady=4)

        tab1 = ttk.Frame(self.notebook)
        tab2 = ttk.Frame(self.notebook)
        self.notebook.add(tab1, text="  Debugger  ")
        self.notebook.add(tab2, text="  Logs & Hooks  ")

        # Build logs tab immediately so widgets exist before threads start
        self._build_logs_tab(tab2)

        # Main Layout (tab1)
        main_container = ttk.Frame(tab1)
        main_container.pack(fill="both", expand=True, padx=3, pady=3)

        # Two column layout
        left_col = ttk.Frame(main_container)
        left_col.pack(side="left", fill="both", expand=True, padx=2)

        right_col = ttk.Frame(main_container)
        right_col.pack(side="right", fill="both", expand=True, padx=2)

        # --- LEFT COLUMN: STATE & INV ---
        self.player_frame = ttk.LabelFrame(left_col, text=" PLAYER ", padding=5)
        self.player_frame.pack(fill="x", pady=2)
        self.player_stats = self.create_simple_stat_grid(self.player_frame)

        self.npc_frame = ttk.LabelFrame(left_col, text=" TARGET NPC ", padding=5)
        self.npc_frame.pack(fill="x", pady=2)
        self.npc_stats = self.create_simple_stat_grid(self.npc_frame)

        self.inv_frame = ttk.LabelFrame(left_col, text=" INVENTORY ", padding=5)
        self.inv_frame.pack(fill="both", expand=True, pady=2)

        self.inv_canvas = tk.Canvas(self.inv_frame, bg="#0A0A0A", highlightthickness=0)
        self.inv_scroll = ttk.Scrollbar(self.inv_frame, orient="vertical", command=self.inv_canvas.yview)
        self.inv_list_frame = ttk.Frame(self.inv_canvas)

        self.inv_canvas.create_window((0, 0), window=self.inv_list_frame, anchor="nw")
        self.inv_canvas.configure(yscrollcommand=self.inv_scroll.set)
        self.inv_canvas.pack(side="left", fill="both", expand=True)
        self.inv_scroll.pack(side="right", fill="y")
        self.inv_list_frame.bind("<Configure>", lambda e: self.inv_canvas.configure(scrollregion=self.inv_canvas.bbox("all")))

        # --- RIGHT COLUMN: ACTIONS ---
        # Dialogue & Broadcast (Combined)
        actions_top = ttk.LabelFrame(right_col, text=" DIALOGUE & BROADCAST ", padding=5)
        actions_top.pack(fill="x", pady=2)

        self.msg_entry = tk.Text(actions_top, height=3, bg="#1A1A1A", fg="#BBBBBB", font=("Consolas", 9), insertbackground="white")
        self.msg_entry.pack(fill="x", pady=2)
        self.msg_entry.insert("1.0", "Hello there, drifter.")

        btn_row1 = ttk.Frame(actions_top)
        btn_row1.pack(fill="x")
        ttk.Button(btn_row1, text="PLAYER SAY", command=lambda: self.send_pipe(f"PLAYER_SAY: {self.msg_entry.get('1.0', tk.END).strip()}")).pack(side="left", fill="x", expand=True)
        ttk.Button(btn_row1, text="NPC SAY", command=lambda: self.send_pipe(f"NPC_SAY: {self.msg_entry.get('1.0', tk.END).strip()}")).pack(side="right", fill="x", expand=True)

        btn_row2 = ttk.Frame(actions_top)
        btn_row2.pack(fill="x", pady=2)
        ttk.Button(btn_row2, text="NOTIFY", command=lambda: self.send_pipe(f"NOTIFY: {self.msg_entry.get('1.0', tk.END).strip()}")).pack(fill="x", expand=True)

        # Combat & Actions
        actions_frame = ttk.LabelFrame(right_col, text=" ACTIONS & SQUAD ", padding=5)
        actions_frame.pack(fill="x", pady=2)
        ttk.Button(actions_frame, text="RECRUIT", style="Success.TButton", command=lambda: self.send_action("[ACTION: JOIN_PARTY]")).pack(fill="x", pady=1)
        ttk.Button(actions_frame, text="ATTACK", style="Danger.TButton", command=lambda: self.send_action("[ACTION: ATTACK]")).pack(fill="x", pady=1)

        def safe_dismiss():
            faction = getattr(self, 'current_npc_faction', "Unknown")
            if faction and faction != "Unknown":
                self.send_action(f"[ACTION: LEAVE: {faction}]")
            else:
                self.send_action("[ACTION: LEAVE]")

        ttk.Button(actions_frame, text="DISMISS", command=safe_dismiss).pack(fill="x", pady=1)

        # New specialized behavior buttons
        btn_behavior = ttk.Frame(actions_frame)
        btn_behavior.pack(fill="x", pady=2)
        ttk.Button(btn_behavior, text="FOLLOW", style="Success.TButton", command=lambda: self.send_action("[ACTION: FOLLOW_PLAYER]")).pack(side="left", fill="x", expand=True, padx=(0, 1))
        ttk.Button(btn_behavior, text="IDLE", command=lambda: self.send_action("[ACTION: IDLE]")).pack(side="left", fill="x", expand=True, padx=1)
        ttk.Button(btn_behavior, text="PATROL", command=lambda: self.send_action("[ACTION: PATROL_TOWN]")).pack(side="left", fill="x", expand=True, padx=(1, 0))

        btn_behavior2 = ttk.Frame(actions_frame)
        btn_behavior2.pack(fill="x", pady=2)
        ttk.Button(btn_behavior2, text="RELEASE PLAYER", command=lambda: self.send_action("[ACTION: RELEASE_PLAYER]")).pack(fill="x")

        # Money
        cats_frame = ttk.LabelFrame(right_col, text=" CATS ", padding=5)
        cats_frame.pack(fill="x", pady=2)
        self.cat_entry = tk.Entry(cats_frame, bg="#1A1A1A", fg="#FFD700", font=("Consolas", 9), insertbackground="white")
        self.cat_entry.pack(fill="x", pady=2)
        self.cat_entry.insert(0, "1000")
        btn_row3 = ttk.Frame(cats_frame)
        btn_row3.pack(fill="x")
        ttk.Button(btn_row3, text="GIVE", style="Money.TButton", command=lambda: self.send_action(f"[ACTION: GIVE_CATS: {self.cat_entry.get()}]")).pack(side="left", fill="x", expand=True)
        ttk.Button(btn_row3, text="TAKE", style="Money.TButton", command=lambda: self.send_action(f"[ACTION: TAKE_CATS: {self.cat_entry.get()}]")).pack(side="right", fill="x", expand=True)

        # AI Goals
        task_frame = ttk.LabelFrame(right_col, text=" NPC GOAL ", padding=5)
        task_frame.pack(fill="x", pady=2)
        self.task_var = tk.StringVar()
        self.task_combo = ttk.Combobox(task_frame, textvariable=self.task_var, state="readonly", font=("Segoe UI", 8))
        self.task_combo['values'] = ["IDLE", "WANDERER", "PATROL_TOWN", "RUN_AWAY", "FOLLOW_PLAYER_ORDER", "MELEE_ATTACK"]
        self.task_combo.set("IDLE")
        self.task_combo.pack(fill="x", pady=2)
        ttk.Button(task_frame, text="SET GOAL", command=self.send_task).pack(fill="x")

        # Faction Relations
        faction_frame = ttk.LabelFrame(right_col, text=" FACTION RELATIONS ", padding=5)
        faction_frame.pack(fill="x", pady=2)

        self.faction_val_entry = tk.Entry(faction_frame, bg="#1A1A1A", fg="#00D2FF", font=("Consolas", 9), insertbackground="white")
        self.faction_val_entry.pack(fill="x", pady=2)
        self.faction_val_entry.insert(0, "10")

        btn_row_f = ttk.Frame(faction_frame)
        btn_row_f.pack(fill="x")
        ttk.Button(btn_row_f, text="SET RELATION", style="Success.TButton", command=self.send_faction_rel).pack(fill="x")

        # Spawn Item Section
        spawn_frame = ttk.LabelFrame(right_col, text=" SPAWN ITEM ", padding=5)
        spawn_frame.pack(fill="x", pady=2)
        self.spawn_template = tk.Entry(spawn_frame, bg="#1A1A1A", fg="#BBBBBB", font=("Consolas", 8))
        self.spawn_template.pack(fill="x")
        self.spawn_template.insert(0, "Book")

        self.spawn_name = tk.Entry(spawn_frame, bg="#1A1A1A", fg="#BBBBBB", font=("Consolas", 8))
        self.spawn_name.pack(fill="x")
        self.spawn_name.insert(0, "Bounty Post")

        self.spawn_desc = tk.Text(spawn_frame, height=2, bg="#1A1A1A", fg="#BBBBBB", font=("Consolas", 8))
        self.spawn_desc.pack(fill="x", pady=2)
        self.spawn_desc.insert("1.0", "WANTED: Red Sabre Leader")

        ttk.Button(spawn_frame, text="SPAWN", command=self.send_spawn).pack(fill="x")

        # Take Item Section
        take_item_frame = ttk.LabelFrame(right_col, text=" TAKE ITEM FROM PLAYER ", padding=5)
        take_item_frame.pack(fill="x", pady=2)
        self.take_item_name = tk.Entry(take_item_frame, bg="#1A1A1A", fg="#BBBBBB", font=("Consolas", 8))
        self.take_item_name.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.take_item_name.insert(0, "Raw Meat")
        ttk.Button(take_item_frame, text="TAKE", command=lambda: self.send_action(f"[ACTION: TAKE_ITEM: {self.take_item_name.get()}]")).pack(side="right")

        # --- TIMERS SECTION ---
        timer_frame = ttk.LabelFrame(right_col, text=" AI TIMERS ", padding=5)
        timer_frame.pack(fill="x", pady=2)

        self.radiant_timer_lbl = ttk.Label(timer_frame, text="Radiant: -- / --", font=("Consolas", 8))
        self.radiant_timer_lbl.pack(fill="x")
        self.radiant_progress = ttk.Progressbar(timer_frame, length=100, mode='determinate')
        self.radiant_progress.pack(fill="x", pady=(0, 5))

        self.synthesis_timer_lbl = ttk.Label(timer_frame, text="Synthesis: -- / --m", font=("Consolas", 8))
        self.synthesis_timer_lbl.pack(fill="x")
        self.synthesis_progress = ttk.Progressbar(timer_frame, length=100, mode='determinate')
        self.synthesis_progress.pack(fill="x", pady=(0, 5))

        self.speech_timer_lbl = ttk.Label(timer_frame, text="Speech Delay: -- / --s", font=("Consolas", 8))
        self.speech_timer_lbl.pack(fill="x")
        self.speech_progress = ttk.Progressbar(timer_frame, length=100, mode='determinate')
        self.speech_progress.pack(fill="x", pady=(0, 2))

        # System Backend
        system_frame = ttk.LabelFrame(right_col, text=" SYSTEM ", padding=5)
        system_frame.pack(fill="x", pady=2)

        # Provider Selection
        self.provider_var = tk.StringVar()
        self.provider_combo = ttk.Combobox(system_frame, textvariable=self.provider_var, state="readonly", font=("Segoe UI", 8))
        self.provider_combo.pack(fill="x", pady=2)
        self.provider_combo.bind("<<ComboboxSelected>>", self.on_provider_change)

        # Model Selection
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(system_frame, textvariable=self.model_var, state="readonly", font=("Segoe UI", 8))
        self.model_combo.pack(fill="x", pady=1)
        self.model_combo.bind("<<ComboboxSelected>>", self.change_model)

        # Radiant Dialogue Toggle
        self.ambient_var = tk.BooleanVar(value=True)
        self.ambient_check = ttk.Checkbutton(system_frame, text="Radiant Dialogue", variable=self.ambient_var, command=self.toggle_ambient)
        self.ambient_check.pack(fill="x", pady=2)

        self.all_models_data = {}  # Full dict from server

        debug_frame = ttk.Frame(system_frame)
        debug_frame.pack(fill="x", pady=2)
        ttk.Button(debug_frame, text="BANTER", command=lambda: self.send_pipe("CMD: TRIGGER_AMBIENT")).pack(side="left", fill="x", expand=True)
        ttk.Button(debug_frame, text="TRACE", command=lambda: self.send_pipe("CMD: TRACE_CONTEXT")).pack(side="right", fill="x", expand=True)

    def _build_logs_tab(self, parent):
        """Full-height Logs tab: Server Log + Events Log side-by-side, hooks below."""
        # Top half: Server Log (left) + Events Log (right)
        top = ttk.Frame(parent)
        top.pack(fill="both", expand=True, padx=4, pady=4)

        # --- LLM Server Log ---
        log_frame = ttk.LabelFrame(top, text=" LLM SERVER LOG ", padding=4)
        log_frame.pack(side="left", fill="both", expand=True, padx=(0, 3))

        log_hdr = ttk.Frame(log_frame)
        log_hdr.pack(fill="x", pady=(0, 2))
        self.server_status_dot = ttk.Label(log_hdr, text="● OFFLINE",
                                           foreground="#FF5555", font=("Consolas", 8, "bold"))
        self.server_status_dot.pack(side="left")
        ttk.Button(log_hdr, text="CLEAR", width=6,
                   command=self._clear_server_log).pack(side="right")

        self.server_log = scrolledtext.ScrolledText(
            log_frame, bg="#050508", fg="#AAFFAA",
            font=("Consolas", 8), borderwidth=0, wrap="none", state="disabled")
        self.server_log.tag_configure("error", foreground="#FF5555")
        self.server_log.tag_configure("warn", foreground="#FFD700")
        self.server_log.tag_configure("info", foreground="#AAFFAA")
        self.server_log.tag_configure("debug", foreground="#555566")
        self.server_log.pack(fill="both", expand=True)

        # --- Actions / Global Events Log ---
        evt_frame = ttk.LabelFrame(top, text=" TRACKED ACTIONS & EVENTS ", padding=4)
        evt_frame.pack(side="right", fill="both", expand=True, padx=(3, 0))

        evt_hdr = ttk.Frame(evt_frame)
        evt_hdr.pack(fill="x", pady=(0, 2))
        ttk.Label(evt_hdr, text="Live feed from engine hooks",
                  font=("Consolas", 7), foreground="#666666").pack(side="left")
        ttk.Button(evt_hdr, text="CLEAR", width=6,
                   command=self._clear_events_log).pack(side="right")

        self.events_log = scrolledtext.ScrolledText(
            evt_frame, bg="#050508", fg="#BBBBBB",
            font=("Consolas", 8), borderwidth=0, wrap="char", state="disabled")
        self.events_log.tag_configure("combat", foreground="#FF5555")
        self.events_log.tag_configure("heal", foreground="#55FF88")
        self.events_log.tag_configure("trade", foreground="#FFD700")
        self.events_log.tag_configure("raid", foreground="#FF8800")
        self.events_log.tag_configure("city", foreground="#00D2FF")
        self.events_log.tag_configure("default", foreground="#BBBBBB")
        self.events_log.pack(fill="both", expand=True)

        # --- Engine Hooks table (bottom strip, full width) ---
        hooks_frame = ttk.LabelFrame(parent, text=" ENGINE HOOKS (ACTIVE) ", padding=4)
        hooks_frame.pack(fill="x", padx=4, pady=(0, 4))
        self.hooks_text = scrolledtext.ScrolledText(
            hooks_frame, height=9, bg="#050508", fg="#00D2FF",
            font=("Consolas", 8), borderwidth=0, wrap="none", state="disabled")
        self.hooks_text.pack(fill="x")
        self.root.after(100, self.populate_hooks)

    def create_simple_stat_grid(self, parent):
        widgets = {}
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill="x")

        widgets['name'] = ttk.Label(header_frame, text="Unknown", font=("Segoe UI", 10, "bold"))
        widgets['name'].pack(side="left")

        widgets['money'] = ttk.Label(header_frame, text="0c", style="Money.TLabel")
        widgets['money'].pack(side="right")

        # New: Faction and Relation labels
        fact_frame = ttk.Frame(parent)
        fact_frame.pack(fill="x")
        widgets['faction'] = ttk.Label(fact_frame, text="Neutral", foreground="#4FB0FF", font=("Segoe UI", 9, "italic"))
        widgets['faction'].pack(side="left")

        widgets['relation'] = ttk.Label(fact_frame, text="REL: --", foreground="#FFD700", font=("Consolas", 9, "bold"))
        widgets['relation'].pack(side="right")

        widgets['race'] = ttk.Label(parent, text="--", font=("Consolas", 8))
        widgets['race'].pack(fill="x")

        grid_frame = ttk.Frame(parent)
        grid_frame.pack(fill="x", pady=2)

        stats = [("S", "strength"), ("D", "dexterity"), ("T", "toughness"), ("P", "perception")]
        for i, (label, key) in enumerate(stats):
            ttk.Label(grid_frame, text=f"{label}:", width=2).grid(row=0, column=i * 2, sticky="w")
            widgets[key] = ttk.Label(grid_frame, text="--", style="Stat.TLabel", width=3)
            widgets[key].grid(row=0, column=i * 2 + 1, sticky="w", padx=(0, 5))

        health_frame = ttk.Frame(parent)
        health_frame.pack(fill="x")
        ttk.Label(health_frame, text="Bld:").pack(side="left")
        widgets['blood'] = ttk.Label(health_frame, text="--", style="Health.TLabel")
        widgets['blood'].pack(side="left", padx=(2, 10))

        ttk.Label(health_frame, text="Hgr:").pack(side="left")
        widgets['hunger'] = ttk.Label(health_frame, text="--", style="Health.TLabel")
        widgets['hunger'].pack(side="left", padx=2)

        return widgets

    def poll_server(self):
        while self.running:
            try:
                resp = requests.get("http://localhost:5000/context", timeout=1)
                if resp.status_code == 200:
                    data = resp.json()
                    self.root.after(0, self.update_display, data)
            except:
                pass
            time.sleep(0.5)

    # ---- Server Log File Tail ----
    _LOG_PATH = os.path.join(KENSHI_SERVER_DIR, "logs", "server.log")

    def poll_log_file(self):
        """Tail server.log from disk. No HTTP endpoint required."""
        last_size = 0
        while self.running:
            try:
                if os.path.exists(self._LOG_PATH):
                    size = os.path.getsize(self._LOG_PATH)
                    if size != last_size:
                        with open(self._LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
                            if size > last_size:
                                f.seek(last_size)      # only read new bytes
                            else:
                                f.seek(0)              # file was rotated/truncated
                            new_text = f.read()
                        last_size = size
                        if new_text:
                            self.root.after(0, self._append_server_log, new_text)
                    # Update status dot based on whether file exists and is recent
                    mtime = os.path.getmtime(self._LOG_PATH)
                    alive = (time.time() - mtime) < 30
                    dot = "● ONLINE" if alive else "● IDLE"
                    col = "#00FF88" if alive else "#FFD700"
                    self.root.after(0, self.server_status_dot.config, {"text": dot, "foreground": col})
                else:
                    self.root.after(0, self.server_status_dot.config,
                                    {"text": "● OFFLINE", "foreground": "#FF5555"})
            except Exception:
                pass
            time.sleep(2)

    def _append_server_log(self, text):
        self.server_log.config(state="normal")
        for line in text.splitlines():
            tag = "info"
            if " - ERROR - " in line:
                tag = "error"
            elif " - WARNING - " in line:
                tag = "warn"
            elif " - DEBUG - " in line:
                tag = "debug"
            self.server_log.insert(tk.END, line + "\n", tag)
        # Keep only last 200 visible lines
        line_count = int(self.server_log.index(tk.END).split('.')[0])
        if line_count > 210:
            self.server_log.delete("1.0", f"{line_count - 200}.0")
        self.server_log.see(tk.END)
        self.server_log.config(state="disabled")

    def _clear_server_log(self):
        self.server_log.config(state="normal")
        self.server_log.delete("1.0", tk.END)
        self.server_log.config(state="disabled")

    # ---- Global Events Log (tails global_events.log) ----
    _EVENTS_LOG_PATH = os.path.join(KENSHI_SERVER_DIR, "campaigns", "Default", "logs", "global_events.log")

    def poll_events_file(self):
        """Tail global_events.log which the server writes on every engine hook trigger."""
        last_size = 0
        while self.running:
            try:
                if os.path.exists(self._EVENTS_LOG_PATH):
                    size = os.path.getsize(self._EVENTS_LOG_PATH)
                    if size != last_size:
                        with open(self._EVENTS_LOG_PATH, 'r', encoding='utf-8', errors='replace') as f:
                            f.seek(last_size if size > last_size else 0)
                            new_text = f.read()
                        last_size = size
                        if new_text:
                            self.root.after(0, self._append_events_log, new_text)
            except Exception:
                pass
            time.sleep(1.5)

    def _append_events_log(self, text):
        self.events_log.config(state="normal")
        for line in text.splitlines():
            tag = "default"
            lo = line.lower()
            if "[combat]" in lo:
                tag = "combat"
            elif "[healing]" in lo:
                tag = "heal"
            elif "[trade]" in lo:
                tag = "trade"
            elif "[raid]" in lo:
                tag = "raid"
            elif "[city_transfer]" in lo:
                tag = "city"
            self.events_log.insert(tk.END, line + "\n", tag)
        line_count = int(self.events_log.index(tk.END).split('.')[0])
        if line_count > 510:
            self.events_log.delete("1.0", f"{line_count - 500}.0")
        self.events_log.see(tk.END)
        self.events_log.config(state="disabled")

    def _clear_events_log(self):
        self.events_log.config(state="normal")
        self.events_log.delete("1.0", tk.END)
        self.events_log.config(state="disabled")

    # ---- Engine Hooks Table ----
    HOOKS = [
        ("attackingYou_hook", "0x9266E0", "Combat Initiation"),
        ("applyDamage_hook", "0x4DA9C0", "Damage Detection"),
        ("applyFirstAid_hook", "0x4F0900", "Healing Interaction"),
        ("buyItem_hook", "0x56E0B0", "Trade / Transaction"),
        ("triggerCampaign_hook", "0x175620", "Raid / War Systems"),
        ("setFaction_hook", "0x927020", "City Ownership"),
        ("playerUpdate_hook", "varies", "Main UI / Action Loop"),
    ]

    def populate_hooks(self):
        self.hooks_text.config(state="normal")
        self.hooks_text.delete("1.0", tk.END)
        self.hooks_text.insert(tk.END, f"{'FUNCTION':<25} {'VMA':<10} EVENT TYPE\n")
        self.hooks_text.insert(tk.END, "─" * 56 + "\n")
        for name, vma, etype in self.HOOKS:
            self.hooks_text.insert(tk.END, f"✓ {name:<23} {vma:<10} {etype}\n")
        self.hooks_text.config(state="disabled")

    def update_display(self, data):
        player = data.get("player", {})
        npc = data.get("npc", {})
        campaign = data.get("campaign", "Default")

        if campaign != self.current_campaign:
            self.current_campaign = campaign
            self.campaign_lbl.config(text=f"CAMPAIGN: {campaign}")
            # Update log path to campaign-specific log
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self._EVENTS_LOG_PATH = os.path.join(KENSHI_SERVER_DIR, "campaigns", campaign, "logs", "global_events.log")
            self._append_server_log(f"\n[DEBUGGER] Switched to campaign: {campaign}\n")
            self._append_server_log(f"[DEBUGGER] Tailing: {self._EVENTS_LOG_PATH}\n")

        # Update Timers
        def update_timers(data):
            # Try to get timer data from player or npc context if not at top level
            ctx = data.get("player", {}) or data.get("npc", {})

            # Radiant Timer
            rad_now = ctx.get("radiant_timer_ms", 0)
            rad_total = ctx.get("radiant_interval_ms", 120000)  # Default 120s if missing
            self.radiant_timer_lbl.config(text=f"Radiant Banter: {rad_now // 1000}s / {rad_total // 1000}s")
            self.radiant_progress['value'] = min(100, (rad_now / rad_total) * 100)

            # Synthesis Timer (Python side, top level)
            synth = data.get("synthesis", {})
            syn_now = synth.get("elapsed", 0)
            syn_total = synth.get("interval", 60)
            self.synthesis_timer_lbl.config(text=f"Narrative Synthesis: {syn_now}m / {syn_total}m")
            self.synthesis_progress['value'] = min(100, (syn_now / syn_total) * 100)

            # Speech Delay Timer (NPC speech spacing)
            speech_now = ctx.get("speech_delay_ms", 0)
            speech_total = ctx.get("speech_interval_ms", 5000)  # Default 5s if missing
            self.speech_timer_lbl.config(text=f"Speech Delay: {speech_now / 1000:.1f}s / {speech_total / 1000:.1f}s")
            self.speech_progress['value'] = min(100, (speech_now / speech_total) * 100)

        update_timers(data)

        def fill_stats(widgets, ctx):
            widgets['name'].config(text=ctx.get("name", "Unknown"))
            widgets['race'].config(text=f"[{ctx.get('race', '--')}]")
            widgets['money'].config(text=f"{ctx.get('money', 0)} cats")

            # Update Faction and Relation
            widgets['faction'].config(text=ctx.get("faction", "Neutral"))
            rel = ctx.get("relation", "--")
            if isinstance(rel, (int, float)):
                widgets['relation'].config(text=f"REL: {int(rel)}")
                if rel > 25:
                    widgets['relation'].config(foreground="#00FF00")
                elif rel < -25:
                    widgets['relation'].config(foreground="#FF5555")
                else:
                    widgets['relation'].config(foreground="#FFD700")

            s = ctx.get("stats", {})
            for key in ['strength', 'dexterity', 'toughness', 'perception']:
                if key in s and key in widgets:
                    widgets[key].config(text=str(int(float(s[key]))))
            m = ctx.get("medical", {})
            widgets['blood'].config(text=str(int(m.get("blood", 0))))
            widgets['hunger'].config(text=str(int(m.get("hunger", 0))))

        if player:
            fill_stats(self.player_stats, player)
        if npc:
            fill_stats(self.npc_stats, npc)
            self.current_npc_faction = npc.get("factionID", npc.get("faction", "Neutral"))
            self.current_npc_name = npc.get("name", "Unknown")
            self.current_npc_id = npc.get("id", 0)

        inv = npc.get("inventory", [])
        for widget in self.inv_list_frame.winfo_children():
            widget.destroy()
        if inv:
            for item in inv:
                item_row = ttk.Frame(self.inv_list_frame, padding=2)
                item_row.pack(fill="x", pady=1)
                name, count, equipped, slot = item['name'], item['count'], item.get('equipped', False), item.get('slot', 'none')
                lbl = ttk.Label(item_row, text=f"{name} (x{count})" + (f" [{slot.upper()}]" if equipped else ""), width=35)
                if equipped:
                    lbl.config(foreground="#AAFFAA")
                lbl.pack(side="left")
                ttk.Button(item_row, text="GIVE", width=6, command=lambda n=name: self.send_action(f"[ACTION: GIVE_ITEM: {n}]")).pack(side="right", padx=2)
                ttk.Button(item_row, text="DROP", width=6, command=lambda n=name: self.send_action(f"[ACTION: DROP_ITEM: {n}]")).pack(side="right", padx=2)

    def load_models(self):
        """Fetch model/provider list from server asynchronously."""
        def _fetch(attempt=1):
            try:
                resp = requests.get("http://localhost:5000/models", timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    self.root.after(0, self._apply_models, data)
                    return
            except Exception:
                pass
            # Retry once after 3s if server wasn't ready
            if attempt == 1:
                time.sleep(3)
                _fetch(attempt=2)
            else:
                self.root.after(0, self.status_lbl.config,
                                {"text": "API Connection: FAILED (Server Offline?)", "foreground": "#FF5555"})

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_models(self, data):
        """Apply fetched model data to UI controls (must run on main thread)."""
        self.all_models_data = data.get("models", {})
        providers = data.get("providers", [])
        current = data.get("current", "")
        enable_ambient = data.get("enable_ambient", True)

        self.provider_combo['values'] = providers
        self.ambient_var.set(enable_ambient)

        # Determine current provider from current model key
        current_provider = ""
        if current in self.all_models_data:
            current_provider = self.all_models_data[current].get("provider", "")
        if not current_provider and providers:
            current_provider = providers[0]

        if current_provider:
            # Must call set() THEN manually call on_provider_change because
            # programmatic set() on a readonly Combobox doesn't fire <<ComboboxSelected>>
            self.provider_var.set(current_provider)
            self.update_model_list(current_provider)
            # Now set the specific model
            models = self.model_combo['values']
            if current in models:
                self.model_var.set(current)
            elif models:
                self.model_var.set(models[0])

        self.status_lbl.config(
            text=f"API: OK | Provider: {current_provider} | Model: {self.model_var.get()}",
            foreground="#00FF00")

    def on_provider_change(self, event=None):
        provider = self.provider_var.get()
        self.update_model_list(provider)
        # Select first model in list automatically
        models = self.model_combo['values']
        if models:
            self.model_var.set(models[0])
            self.change_model()

    def update_model_list(self, provider):
        models = [name for name, info in self.all_models_data.items() if info.get("provider") == provider]
        self.model_combo['values'] = sorted(models)

    def change_model(self, event=None):
        new_model = self.model_var.get()
        threading.Thread(target=lambda m=new_model: requests.post("http://localhost:5000/settings", json={"current_model": m}, timeout=5), daemon=True).start()

    def toggle_ambient(self):
        state = self.ambient_var.get()
        threading.Thread(target=lambda s=state: requests.post("http://localhost:5000/settings", json={"enable_ambient": s}, timeout=5), daemon=True).start()

    def send_task(self):
        task = self.task_var.get()
        if task:
            self.send_action(f"[ACTION:TASK:{task}]")

    def send_faction_rel(self):
        val = self.faction_val_entry.get().strip()
        if self.current_npc_faction and val:
            self.send_action(f"[ACTION:FACTION_RELATIONS:{self.current_npc_faction}:{val}]")

    def send_spawn(self):
        tpl = self.spawn_template.get()
        name = self.spawn_name.get()
        desc = self.spawn_desc.get("1.0", tk.END).strip()
        self.send_action(f"[ACTION: SPAWN_ITEM: {tpl} | {name} | {desc}]")

    def send_action(self, action_tag):
        self.send_pipe("NPC_ACTION: " + action_tag)

    def send_pipe(self, msg):
        try:
            # Inject identity header for NPC actions/speech if we have a target
            if msg.startswith("NPC_") and hasattr(self, 'current_npc_name') and self.current_npc_name != "Unknown":
                header = f"{self.current_npc_name}|{self.current_npc_id}: "
                if msg.startswith("NPC_SAY: "):
                    msg = "NPC_SAY: " + header + msg[9:]
                elif msg.startswith("NPC_ACTION: "):
                    msg = "NPC_ACTION: " + header + msg[12:]

            with open(r'\\.\pipe\SentientSands', 'wb') as f:
                f.write(msg.encode('utf-8'))
            self.status_lbl.config(text=f"SUCCESS: {msg[:50]}...", foreground="#00FF00")
        except Exception as e:
            self.status_lbl.config(text=f"PIPE ERROR: {str(e)}", foreground="#FF5555")


if __name__ == "__main__":
    try:
        app = VisualDebugger()
        app.root.mainloop()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(err_msg)  # Print to console if it's still alive

        # Try to show a GUI error if tkinter initialized
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Visual Debugger - Startup Error",
                                 f"Failed to start debugger:\n\n{str(e)}\n\nSee console for traceback.")
            root.destroy()
        except:
            pass
