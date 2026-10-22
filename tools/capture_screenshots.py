"""Capture only this app's UI. No game binding, global hotkeys or playback."""
import argparse
import ctypes
import os
from pathlib import Path
import sys
import tkinter as tk

from PIL import ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["ROCO_MUSIC_DATA"] = str(ROOT / ".vendor/screenshot-data")
from rocomusic.app import App
from rocomusic.catalog import BASE, parse_library
from rocomusic.score import Note, Score, UnsupportedNotes, load_file
from rocomusic.ui import Tooltip


class PreviewApp(App):
    def refresh_windows(self):
        # Constructor leaves Player attached to NoTarget. Never enumerate games.
        self.windows = []
        self.window_box["values"] = ()
        self.window_label.set("界面截图 · 未连接游戏")
        self.permission_label.set("界面预览：未绑定游戏，未注册全局快捷键，不发送音键。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-snapshot", type=Path, help="Optional previously saved public /library HTML; no network access")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/screenshots")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    root = tk.Tk()
    # A stationary real mouse must not cover the app-only screenshot with a tip.
    Tooltip.schedule = lambda *_: None
    app = PreviewApp(root, hotkeys=False, auto_search=False, check_updates=False)
    if args.catalog_snapshot:
        result = parse_library(args.catalog_snapshot.read_text(encoding="utf-8"), 1, BASE + "/library")
        app.entries, app.pages = result.entries, result.pages
        for i, entry in enumerate(result.entries):
            app.tree.insert("", "end", iid=str(i), values=(entry.title, entry.author, entry.format.upper(), entry.category))
        app.page_label.configure(text=f"1 / {result.pages} 页")
    score = load_file(ROOT / "samples/nine-key-check.mid")
    score.title = "九键手碟示例"
    app._set_score(score)
    app.catalog_label.set("界面截图 · 列表使用公开曲库快照 · 未启动演奏")
    root.update_idletasks()
    height = min(930, root.winfo_screenheight() - 70)
    root.geometry(f"1080x{height}")
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - root.winfo_width()) // 2)
    y = max(0, root.winfo_screenheight() - root.winfo_height() - 45)
    root.geometry(f"+{x}+{y}")
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()

    def capture(name, window=None):
        window = window or root
        root.update_idletasks()
        x, y = window.winfo_rootx(), window.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + window.winfo_width(), y + window.winfo_height())).save(args.output / name)

    def post(widget):
        root.tk.call("ttk::combobox::Post", str(widget))
        if widget is app.speed_box:
            # Keep the native popdown inside the app-only capture rectangle.
            popup = root.tk.call("ttk::combobox::PopdownWindow", str(widget))
            root.update_idletasks()
            height = int(root.tk.call("winfo", "reqheight", popup))
            root.tk.call("wm", "geometry", popup, f"+{widget.winfo_rootx()}+{widget.winfo_rooty() - height}")

    def unpost(widget):
        root.tk.call("ttk::combobox::Unpost", str(widget))

    def main_image():
        capture("main.png")
        post(app.filter_boxes["category"])
        root.after(400, filter_image)

    def filter_image():
        capture("filters.png")
        unpost(app.filter_boxes["category"])
        post(app.speed_box)
        root.after(400, speed_image)

    def speed_image():
        capture("speeds.png")
        unpost(app.speed_box)
        app.open_updates()  # No check/download. Only render the actual idle window.
        root.after(400, update_image)

    def update_image():
        capture("updates.png", app.update_window.win)
        app.update_window.close()
        # Example explanation only; never load or play an unsupported score.
        sample = Score("普通钢琴 MIDI（说明示例）", [Note(65, 0, .5)] * 44 + [Note(72, 1, .5)] * 958, 2)
        app._clear_score()
        app._show_error(UnsupportedNotes(sample))
        root.after(400, error_image)

    def error_image():
        capture("needs-conversion.png", app.error_window)
        app.error_window.destroy()
        app.error_window = None
        app.close()

    root.after(800, main_image)
    try:
        root.mainloop()
    finally:
        app.close()


if __name__ == "__main__":
    main()
