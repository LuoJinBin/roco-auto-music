from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback
import webbrowser

from .catalog import CatalogClient, FILTER_OPTIONS, SiteBlocked
from .native import Hotkeys, InputError, NativeSink, list_windows, permission_issue
from .device_input import DeviceSink, driver_registered
from .player import Player, timing_summary
from .score import KEY_MAP, SPEEDS, ScoreError, load_file


def data_directory():
    if os.environ.get("ROCO_MUSIC_DATA"):
        return Path(os.environ["ROCO_MUSIC_DATA"])
    return Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / "RocoAutoMusic"


class NoTarget:
    target = None
    held = set()
    def ready(self): return False
    def begin(self): raise InputError("请先选择游戏窗口。")
    def send(self, up=(), down=()): raise InputError("请先选择游戏窗口。")
    def release(self): pass


class App:
    def __init__(self, root: tk.Tk, hotkeys=True, initial_midi=None, auto_search=False):
        self.root = root
        self.data = data_directory()
        self.client = CatalogClient(self.data / "cache")
        self.player = Player(NoTarget(), self.data / "logs")
        self.callbacks = queue.Queue()
        self.control_callbacks = queue.Queue()
        self.busy = False
        self.closed = False
        self.song = None
        self.entries = []
        self.windows = []
        self.page, self.pages, self.last_query = 1, 1, ""
        self.last_filters = {}
        self.last_state = "idle"
        self.last_log_onsets = 0
        self.pulse = tk.IntVar(value=30)
        self.speed_var = tk.StringVar(value="1×")
        self.filter_vars = {name: tk.StringVar(value=choices[0][0]) for name, choices in FILTER_OPTIONS.items()}
        self.mode = tk.StringVar(value="Interception（需驱动）" if driver_registered() else "扫描码（默认）")
        self.confirmed = threading.Event()
        self.arm_var = tk.BooleanVar(value=False)
        self.query = tk.StringVar()
        self.window_label = tk.StringVar()
        self.catalog_label = tk.StringVar(value="默认显示全部曲谱；可按分类、格式、难度、音域和时长筛选。")
        self.permission_label = tk.StringVar()
        self.song_label = tk.StringVar(value="还没有选择曲谱")
        self.details_label = tk.StringVar(value="从在线曲库选择，或导入 .mid / .midi 文件。")
        self.status_label = tk.StringVar(value="选曲后进入游戏九键界面，按 F8 开始。")
        self.time_label = tk.StringVar(value="00:00.0 / 00:00.0")
        self._build()
        self.refresh_windows()
        self.hotkeys = Hotkeys(self._toggle_from_hotkey, self.player.stop) if hotkeys else None
        if self.hotkeys:
            error = self.hotkeys.start()
            if error:
                self.permission_label.set(error)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._callback_error
        self._poll()
        if initial_midi:
            root.after(150, lambda: self.import_file(initial_midi))
        elif auto_search:
            root.after(150, lambda: self.search(1))

    def _build(self):
        r = self.root
        r.title("洛克自动奏乐 · Roco Auto Music")
        r.geometry("1040x870")
        r.minsize(960, 820)
        r.configure(bg="#f4f6f1")
        style = ttk.Style(r)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background="#f4f6f1", foreground="#22392c")
        style.configure("TFrame", background="#f4f6f1")
        style.configure("Card.TLabelframe", background="#ffffff", bordercolor="#dce5d9")
        style.configure("Card.TLabelframe.Label", background="#f4f6f1", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", padding=(13, 7), background="#e7eee4", borderwidth=0)
        style.map("TButton", background=[("active", "#d8e4d3")])
        style.configure("Accent.TButton", background="#296743", foreground="#ffffff", font=("Microsoft YaHei UI", 11, "bold"))
        style.map("Accent.TButton", background=[("active", "#1d5132"), ("disabled", "#a7b5a6")])
        style.configure("Treeview", rowheight=33, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", padding=7, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#dcebdc")], foreground=[("selected", "#173e25")])
        style.configure("TProgressbar", background="#388251", troughcolor="#dde7d8", borderwidth=0)
        wrap = ttk.Frame(r, padding=22)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(2, weight=1)
        header = ttk.Frame(wrap)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ttk.Label(header, text="洛克自动奏乐", font=("Microsoft YaHei UI", 23, "bold")).pack(side="left")
        ttk.Label(header, text="原谱节奏 · 九键手碟", foreground="#63806a").pack(side="left", padx=18, pady=(9, 0))
        ttk.Button(header, text="导入本地 MIDI", command=self.import_file).pack(side="right")
        search = ttk.Frame(wrap)
        search.grid(row=1, column=0, sticky="ew", pady=(0, 9))
        search.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(search, textvariable=self.query, font=("Microsoft YaHei UI", 12))
        self.search_entry.grid(row=0, column=0, sticky="ew", ipady=6)
        self.search_entry.bind("<Return>", lambda _: self.search(1))
        self.search_button = ttk.Button(search, text="搜索曲库", style="Accent.TButton", command=lambda: self.search(1))
        self.search_button.grid(row=0, column=1, padx=(10, 0))
        filters = ttk.Frame(search)
        filters.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.filter_boxes = {}
        labels = {"featured": "曲谱", "category": "分类", "format": "格式", "difficulty": "难度", "sort": "排序", "playable": "音域", "duration": "时长"}
        for column in range(4):
            filters.columnconfigure(column, weight=1, uniform="filter")
        for i, (name, choices) in enumerate(FILTER_OPTIONS.items()):
            cell = ttk.Frame(filters)
            cell.grid(row=i // 4, column=i % 4, sticky="ew", padx=(0, 8), pady=4)
            ttk.Label(cell, text=labels[name]).pack(side="left", padx=(0, 6))
            box = ttk.Combobox(cell, values=tuple(label for label, _ in choices), textvariable=self.filter_vars[name], state="readonly", width=15)
            box.pack(side="left", fill="x", expand=True)
            self.filter_boxes[name] = box
        actions = ttk.Frame(filters)
        actions.grid(row=1, column=3, sticky="e", pady=4)
        self.apply_button = ttk.Button(actions, text="应用筛选", command=lambda: self.search(1))
        self.apply_button.pack(side="left", padx=(0, 6))
        self.clear_button = ttk.Button(actions, text="清除筛选", command=self.clear_filters)
        self.clear_button.pack(side="left")
        catalog = ttk.Frame(wrap)
        catalog.grid(row=2, column=0, sticky="nsew")
        catalog.columnconfigure(0, weight=1)
        catalog.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(catalog, columns=("title", "author", "format", "category"), show="headings", selectmode="browse", height=7)
        for name, label, width in (("title", "曲名", 400), ("author", "分享者", 140), ("format", "格式", 85), ("category", "分类 / 难度", 170)):
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, minwidth=90)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(catalog, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", lambda _: self.load_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _: self._selection_changed())
        bar = ttk.Frame(catalog)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 12))
        self.prev = ttk.Button(bar, text="上一页", command=lambda: self.search(self.page - 1), state="disabled")
        self.prev.pack(side="left")
        self.page_label = ttk.Label(bar, text="1 / 1 页")
        self.page_label.pack(side="left", padx=10)
        self.next = ttk.Button(bar, text="下一页", command=lambda: self.search(self.page + 1), state="disabled")
        self.next.pack(side="left")
        self.load_button = ttk.Button(bar, text="载入所选曲谱", command=self.load_selected, state="disabled")
        self.load_button.pack(side="right")
        ttk.Button(bar, text="网页查看", command=self.open_selected).pack(side="right", padx=8)
        ttk.Label(wrap, textvariable=self.catalog_label, foreground="#617663", wraplength=900).grid(row=3, column=0, sticky="w", pady=(0, 12))
        song = ttk.LabelFrame(wrap, text="当前曲谱", style="Card.TLabelframe", padding=14)
        song.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(song, textvariable=self.song_label, font=("Microsoft YaHei UI", 14, "bold"), wraplength=860).pack(anchor="w")
        ttk.Label(song, textvariable=self.details_label, foreground="#637466", wraplength=860).pack(anchor="w", pady=(5, 0))
        controls = ttk.Frame(wrap)
        controls.grid(row=5, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="游戏窗口").grid(row=0, column=0, padx=(0, 9))
        self.window_box = ttk.Combobox(controls, textvariable=self.window_label, state="readonly")
        self.window_box.grid(row=0, column=1, sticky="ew")
        self.window_box.bind("<<ComboboxSelected>>", lambda _: self.bind_window())
        ttk.Button(controls, text="刷新窗口", command=self.refresh_windows).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(wrap, textvariable=self.permission_label, foreground="#995d24", wraplength=910).grid(row=6, column=0, sticky="ew", pady=(6, 7))
        settings = ttk.Frame(wrap)
        settings.grid(row=7, column=0, sticky="ew", pady=(0, 10))
        ttk.Checkbutton(settings, text="我已进入游戏九键演奏界面", variable=self.arm_var, command=self._arm_changed).pack(side="left")
        ttk.Label(settings, text="按压 ms").pack(side="left", padx=(18, 5))
        self.pulse_box = ttk.Spinbox(settings, from_=10, to=100, increment=5, textvariable=self.pulse, width=5)
        self.pulse_box.pack(side="left")
        self.mode_box = ttk.Combobox(settings, values=("扫描码（默认）", "虚拟键（兼容）", "Interception（需驱动）"), textvariable=self.mode, state="readonly", width=22)
        self.mode_box.pack(side="right")
        self.mode_box.bind("<<ComboboxSelected>>", lambda _: self.bind_window())
        transport = ttk.Frame(wrap)
        transport.grid(row=8, column=0, sticky="ew")
        self.start_button = ttk.Button(transport, text="开始 / 暂停  F8", style="Accent.TButton", command=self.toggle)
        self.start_button.pack(side="left")
        ttk.Button(transport, text="停止  F9", command=self.player.stop).pack(side="left", padx=9)
        ttk.Label(transport, text="倍速").pack(side="left", padx=(12, 6))
        self.speed_box = ttk.Combobox(transport, values=tuple(f"{v:g}×" for v in SPEEDS), textvariable=self.speed_var, state="readonly", width=8)
        self.speed_box.pack(side="left")
        self.speed_box.bind("<<ComboboxSelected>>", lambda _: self._change_speed())
        ttk.Button(transport, text="导出演奏记录", command=self.export_log).pack(side="right")
        self.progress = ttk.Progressbar(wrap, mode="determinate")
        self.progress.grid(row=9, column=0, sticky="ew", pady=(13, 6))
        foot = ttk.Frame(wrap)
        foot.grid(row=10, column=0, sticky="ew")
        ttk.Label(foot, textvariable=self.status_label, wraplength=720).pack(side="left")
        ttk.Label(foot, textvariable=self.time_label).pack(side="right")
        ttk.Label(wrap, text="F8 开始 / 暂停 / 继续    F9 停止    ·    切换窗口自动暂停    ·    默认原谱 1×", foreground="#7c897d", font=("Microsoft YaHei UI", 9)).grid(row=11, column=0, sticky="w", pady=(12, 0))

    def _arm_changed(self):
        if self.arm_var.get():
            self.confirmed.set()
        else:
            self.confirmed.clear()
            self.player.pause("已取消演奏界面确认，暂停发送按键。")

    def refresh_windows(self):
        self.player.stop()
        old = self.window_label.get()
        self.windows = list_windows()
        labels = [w.label for w in self.windows]
        self.window_box["values"] = labels
        self.window_label.set(old if old in labels else labels[0] if labels else "未找到洛克王国游戏窗口")
        self.bind_window()

    def bind_window(self):
        self.player.stop()
        chosen = next((w for w in self.windows if w.label == self.window_label.get()), None)
        with self.player.lock:
            previous = self.player.sink
            if hasattr(previous, "close"):
                previous.close()
            if chosen and self.mode.get().startswith("Interception"):
                self.player.sink = DeviceSink(chosen)
            else:
                self.player.sink = NativeSink(chosen, "virtual" if self.mode.get().startswith("虚拟") else "scan") if chosen else NoTarget()
        self.permission_label.set(permission_issue(chosen))

    def _work(self, label, action, done):
        if self.busy:
            return
        self.player.pause("正在读取曲谱，演奏已暂停。")
        self.busy = True
        self.catalog_label.set(label)
        self.search_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        self.load_button.configure(state="disabled")
        self.prev.configure(state="disabled")
        self.next.configure(state="disabled")
        def task():
            try:
                result = action()
                self.callbacks.put((done, result, None))
            except Exception as exc:
                self.callbacks.put((done, None, exc))
        threading.Thread(target=task, daemon=True, name="roco-network").start()

    def search(self, page=1):
        if self.busy:
            return
        query = self.query.get().strip() if page == 1 else self.last_query
        filters = self._filter_values() if page == 1 else dict(self.last_filters)
        if len(query) > 100:
            messagebox.showerror("搜索词过长", "最多输入 100 字。", parent=self.root)
            return
        def done(result):
            self.entries, self.page, self.pages = result.entries, result.page, result.pages
            self.last_query = query
            self.last_filters = dict(filters)
            self.tree.delete(*self.tree.get_children())
            for i, entry in enumerate(result.entries):
                self.tree.insert("", "end", iid=str(i), values=(entry.title, entry.author, entry.format.upper(), entry.category))
            self.catalog_label.set(f"本页 {len(result.entries)} 首 · {self._filter_summary(filters)} · MIDI 可载入演奏" if result.entries else "未找到匹配曲谱，可清除筛选、换关键词或导入本地 MIDI。")
            self.page_label.configure(text=f"{self.page} / {self.pages} 页")
        self._work("正在读取网站曲库…", lambda: self.client.search(query, page, filters), done)

    def _filter_values(self):
        return {name: dict(choices)[self.filter_vars[name].get()] for name, choices in FILTER_OPTIONS.items()}

    @staticmethod
    def _filter_summary(filters):
        chosen = [label for name, choices in FILTER_OPTIONS.items() for label, value in choices if value and value == filters.get(name)]
        return " · ".join(chosen) if chosen else "全部曲谱 · 不限条件"

    def clear_filters(self):
        if self.busy:
            return
        for name, choices in FILTER_OPTIONS.items():
            self.filter_vars[name].set(choices[0][0])
        self.query.set("")
        if self.client.blocked:
            self.catalog_label.set(self.client.blocked)
        else:
            self.search(1)

    def _selection_changed(self):
        selection = self.tree.selection()
        entry = self.entries[int(selection[0])] if selection else None
        playable = entry is not None and entry.format == "midi" and not self.busy and not self.client.blocked
        self.load_button.configure(state="normal" if playable else "disabled")
        if entry and entry.format != "midi":
            self.catalog_label.set(f"{entry.format.upper()} 曲谱可点击“网页查看”；自动演奏需要 MIDI。")

    def open_selected(self):
        selection = self.tree.selection()
        if selection:
            webbrowser.open(self.entries[int(selection[0])].url)

    def load_selected(self):
        selection = self.tree.selection()
        if not selection or self.busy:
            return
        entry = self.entries[int(selection[0])]
        if entry.format != "midi":
            self.catalog_label.set(f"{entry.format.upper()} 曲谱不能直接演奏，请打开网页查看或转换为 MIDI 后导入。")
            return
        self.player.unload()
        self._work(f"正在下载《{entry.title}》完整 MIDI…", lambda: self.client.load(entry), self._set_score)

    def import_file(self, path=None):
        if self.busy:
            return
        self.player.pause("导入曲谱，已暂停。")
        path = path or filedialog.askopenfilename(parent=self.root, title="导入标准 MIDI 曲谱", filetypes=[("MIDI 曲谱", "*.mid *.midi")])
        if not path:
            return
        self.player.unload()
        self._work("正在解析本地 MIDI…", lambda: load_file(path), self._set_score)

    def _set_score(self, score):
        self.player.load(score, self.pulse.get(), self._speed())
        self.song = score
        self.last_log_onsets = 0
        self.song_label.set(score.title)
        self._update_song_details()
        if score.duplicate_onsets:
            self.catalog_label.set(f"已载入完整曲谱。同一时刻同一音高的 {score.duplicate_onsets} 个重复事件合并为一次物理敲击。")
        else:
            self.catalog_label.set("完整曲谱已载入；演奏期间无需网络。")

    def _speed(self):
        return float(self.speed_var.get().removesuffix("×"))

    def _update_song_details(self):
        if self.song:
            version = f" · 版本 {self.song.version[:8]}" if self.song.version else " · 本地 MIDI"
            self.details_label.set(f"{len(self.song.notes)} 个音符 · 原谱 {format_time(self.song.duration)} · {self.player.speed:g}× · 预计演奏 {format_time(self.player.duration)}{version}")

    def _change_speed(self):
        try:
            self.player.set_speed(self._speed())
            self._update_song_details()
        except Exception as exc:
            self.speed_var.set(f"{self.player.speed:g}×")
            self._show_error(exc)

    def _toggle_from_hotkey(self):
        if self.busy:
            return
        if not self.confirmed.is_set():
            with self.player.lock:
                self.player.message = "请先勾选“我已进入游戏九键演奏界面”。"
            return
        if self.player.state in ("playing", "countdown"):
            self.player.toggle()
        else:
            # Widget values are read only on the Tk thread, including edited pulse length.
            self.control_callbacks.put(self.toggle)

    def toggle(self):
        if self.busy:
            return
        if not self.confirmed.is_set():
            self.status_label.set("请先进入游戏九键演奏界面，再勾选上方确认框。")
            return
        if self.player.state not in ("playing", "countdown"):
            issue = permission_issue(getattr(self.player.sink, "target", None))
            if issue:
                self.permission_label.set(issue)
                self.status_label.set("权限或游戏窗口检查未通过，未发送按键。")
                return
        if self.song and self.player.state in ("idle", "finished", "error"):
            try:
                self.player.load(self.song, self.pulse.get(), self._speed())
                self.last_log_onsets = 0
                self._update_song_details()
            except Exception as exc:
                self._show_error(exc)
                return
        self.player.toggle()

    def export_log(self):
        try:
            path = self.player.export_log()
            self.catalog_label.set(f"演奏记录已保存：{path}")
        except Exception as exc:
            self._show_error(exc)

    def _show_error(self, exc):
        self.catalog_label.set(str(exc))
        messagebox.showerror("未完成", str(exc), parent=self.root)

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                self.control_callbacks.get_nowait()()
            except queue.Empty:
                break
        while True:
            try:
                callback, result, error = self.callbacks.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            try:
                if error:
                    raise error
                callback(result)
            except Exception as exc:
                self._show_error(exc)
            self.search_button.configure(state="disabled" if self.client.blocked else "normal")
            self.apply_button.configure(state="disabled" if self.client.blocked else "normal")
            self.clear_button.configure(state="normal")
            self._selection_changed()
            self.prev.configure(state="normal" if self.page > 1 and not self.client.blocked else "disabled")
            self.next.configure(state="normal" if self.page < self.pages and not self.client.blocked else "disabled")
        s = self.player.snapshot()
        self.status_label.set(f"{s['countdown']} 秒后开始，请切回游戏…" if s["state"] == "countdown" else s["message"])
        self.progress.configure(maximum=max(1, s["source_duration"]), value=s["score_position"])
        self.time_label.set(f"{format_time(s['score_position'])} / {format_time(s['source_duration'])}")
        active = s["state"] in ("playing", "countdown", "paused")
        self.pulse_box.configure(state="disabled" if active else "normal")
        self.mode_box.configure(state="disabled" if active else "readonly")
        if s["state"] != self.last_state and s["state"] in ("finished", "error", "idle") and s["sent"] > self.last_log_onsets:
            try:
                self.player.export_log()
                self.last_log_onsets = s["sent"]
            except OSError:
                pass
        self.last_state = s["state"]
        self.root.after(80, self._poll)

    def _callback_error(self, kind, value, tb):
        self.player.pause("界面异常，演奏已暂停。")
        try:
            self.data.mkdir(parents=True, exist_ok=True)
            (self.data / "error.log").write_text("".join(traceback.format_exception(kind, value, tb)), encoding="utf-8")
        finally:
            self._show_error(value)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.confirmed.clear()
        if self.hotkeys:
            self.hotkeys.close()
        try:
            self.player.close()
        finally:
            self.root.destroy()


def format_time(seconds):
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"
