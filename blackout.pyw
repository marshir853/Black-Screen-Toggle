"""
Blackout - press a hotkey, your screen goes black. Press it again, it comes back.
Everything keeps running underneath.

Setup:   pip install pynput
Run:     python blackout.py
Package: pip install pyinstaller
         pyinstaller --onefile --noconsole blackout.py
"""

import json
import os
import queue
import sys
import tkinter as tk

from pynput import keyboard

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".blackout_hotkey.json")
MODIFIER_ORDER = ["ctrl", "alt", "shift", "cmd"]

# On Windows, make Tk report real pixels (needed for correct multi-monitor size)
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def normalize(key):
    """Turn a pynput key into a simple, layout-stable string name."""
    if isinstance(key, keyboard.Key):
        name = key.name
        for suffix in ("_l", "_r", "_gr"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name
    char = getattr(key, "char", None)
    if char and char.isprintable() and char != " ":
        return char.lower()
    vk = getattr(key, "vk", None)
    if vk is not None:
        if 65 <= vk <= 90:
            return chr(vk).lower()
        if 48 <= vk <= 57:
            return chr(vk)
        return f"vk{vk}"
    return None


def pretty(keys):
    if not keys:
        return "Not set"
    mods = [k for k in MODIFIER_ORDER if k in keys]
    rest = [k for k in keys if k not in MODIFIER_ORDER]
    parts = []
    for k in mods + rest:
        if k.startswith("vk"):
            parts.append(f"Key{k[2:]}")
        else:
            parts.append(k.upper() if len(k) == 1 else k.replace("_", " ").title())
    return " + ".join(parts)


def virtual_screen(root):
    """Return x, y, width, height covering ALL monitors."""
    if sys.platform == "win32":
        u = ctypes.windll.user32
        return u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Blackout")
        self.root.geometry("360x230")
        self.root.resizable(False, False)
        self.root.configure(bg="#14161a")

        self.events = queue.Queue()
        self.hotkey = self.load_hotkey()
        self.recording = False
        self.rec_keys = []
        self.pressed = set()
        self.latched = False
        self.overlay = None

        self.build_ui()

        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.daemon = True
        self.listener.start()

        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(30, self.poll)

    # ---------- UI ----------
    def build_ui(self):
        bg, fg, dim = "#14161a", "#e8e8e8", "#8a8f98"
        tk.Label(self.root, text="BLACKOUT", bg=bg, fg=fg, font=("Segoe UI", 16, "bold")).pack(pady=(18, 2))
        tk.Label(self.root, text="Hotkey toggles a black screen", bg=bg, fg=dim, font=("Segoe UI", 9)).pack()

        self.key_label = tk.Label(self.root, text=pretty(self.hotkey), bg="#1f2229", fg="#ffffff",
                                  font=("Segoe UI", 14, "bold"), width=26, pady=10)
        self.key_label.pack(pady=14)

        self.button = tk.Button(self.root, text="Set Hotkey", command=self.start_recording,
                                bg="#3b82f6", fg="white", activebackground="#2563eb",
                                activeforeground="white", relief="flat", font=("Segoe UI", 10, "bold"),
                                padx=18, pady=6, cursor="hand2", takefocus=0)
        self.button.pack()

        self.status = tk.Label(self.root, text="", bg=bg, fg=dim, font=("Segoe UI", 9))
        self.status.pack(pady=10)

    def start_recording(self):
        self.recording = True
        self.rec_keys = []
        self.pressed.clear()
        self.latched = False
        self.button.config(state="disabled")
        self.key_label.config(text="Press your keys...", bg="#3b2f14")
        self.status.config(text="Press any key or combo, then Tab to save")
        self.root.focus_set()

    def finish_recording(self):
        self.recording = False
        self.button.config(state="normal")
        self.key_label.config(bg="#1f2229")
        if not self.rec_keys:
            self.key_label.config(text=pretty(self.hotkey))
            self.status.config(text="No keys captured, try again")
            return
        self.hotkey = list(self.rec_keys)
        self.save_hotkey()
        self.key_label.config(text=pretty(self.hotkey))
        self.status.config(text="Saved! Minimizing... (hotkey stays active)")
        self.root.after(700, self.root.iconify)

    # ---------- Persistence ----------
    def load_hotkey(self):
        try:
            with open(CONFIG_PATH, "r") as f:
                keys = json.load(f).get("hotkey", [])
                return keys if isinstance(keys, list) else []
        except Exception:
            return []

    def save_hotkey(self):
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump({"hotkey": self.hotkey}, f)
        except Exception:
            pass

    # ---------- Global key listener (runs in its own thread) ----------
    def on_press(self, key):
        name = normalize(key)
        if name is None:
            return
        if self.recording:
            if name == "tab":
                self.events.put("save")
            elif name not in self.rec_keys:
                self.rec_keys.append(name)
                self.events.put("update")
            return
        self.pressed.add(name)
        if self.hotkey and set(self.hotkey) <= self.pressed and not self.latched:
            self.latched = True
            self.events.put("toggle")

    def on_release(self, key):
        name = normalize(key)
        if name is None:
            return
        self.pressed.discard(name)
        if name in self.hotkey:
            self.latched = False

    # ---------- Main-thread event handling ----------
    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event == "update":
                    self.key_label.config(text=pretty(self.rec_keys))
                elif event == "save":
                    self.finish_recording()
                elif event == "toggle":
                    self.toggle_overlay()
        except queue.Empty:
            pass
        self.root.after(30, self.poll)

    def toggle_overlay(self):
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
            return
        x, y, w, h = virtual_screen(self.root)
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.configure(bg="black", cursor="none")
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.attributes("-topmost", True)
        top.update_idletasks()
        top.focus_force()
        self.overlay = top

    def quit(self):
        try:
            self.listener.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
