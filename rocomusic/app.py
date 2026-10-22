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

from .catalog import BASE, CatalogClient, FILTER_OPTIONS, SiteBlocked, SiteError
from .native import Hotkeys, InputError, NativeSink, list_windows, permission_issue
from .device_input import DeviceSink, driver_registered
from .player import Player, timing_summary
from .score import KEY_MAP, SPEEDS, ScoreError, UnsupportedNotes, load_file
from .ui import BG, INK, KingdomBanner, ScrollBody, Tooltip, dialog, readonly_text, show_help
from .updater import UpdateClient, load_preferences
from .update_ui import UpdateWindow
from .version import VERSION


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
    def __init__(self, root: tk.Tk, hotkeys=True, initial_midi=None, auto_search=False, check_updates=True):
        self.root = root
        self.data = data_directory()
        self.client = CatalogClient(self.data / "cache")
        self.player = Player(NoTarget(), self.data / "logs")
        self.callbacks = queue.Queue()
        self.control_callbacks = queue.Queue()
        self.ui_callbacks = queue.Queue()
        self.preferences = load_preferences(self.data)
        self.updater = UpdateClient(self.data / "updates")
        self.update_window = None
        self.update_checking = False
        self.error_window = None
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
        if check_updates and self.preferences["check_on_start"]:
            root.after(1800, self.check_updates_background)

    def _build(self):
        r = self.root
        r.title(f"洛克自动奏乐 · {VERSION}")
        r.geometry("1080x930")
        r.minsize(900, 680)
        r.configure(bg=BG)
        style = ttk.Style(r)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("Card.TLabelframe", bordercolor="#c8dfdf", relief="solid")
        style.configure("Card.TLabelframe.Label", background=BG, foreground="#267d88", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TButton", padding=(11, 6), background="#deeceb", borderwidth=0)
        style.map("TButton", background=[("active", "#c5dfdc")])
        style.configure("Accent.TButton", background="#267d88", foreground="#ffffff", font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#1b606c"), ("disabled", "#9db7bd")], foreground=[("disabled", "#f2f7f8")])
        style.configure("Treeview", rowheight=29, background="#ffffff", fieldbackground="#ffffff", borderwidth=0)
        style.configure("Treeview.Heading", padding=7, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#d7edeb")], foreground=[("selected", "#194b54")])
        style.configure("TProgressbar", background="#42a09b", troughcolor="#dce9e7", borderwidth=0)
        self.scroll_body = ScrollBody(r)
        wrap = self.scroll_body.body
        wrap.columnconfigure(0, weight=1)
        KingdomBanner(wrap).grid(row=0, column=0, sticky="ew")
        header = ttk.Frame(wrap)
        header.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        ttk.Label(header, text="玩家制作 · 非官方工具", foreground="#6e8994", font=("Microsoft YaHei UI", 9)).pack(side="left")
        help_button = ttk.Button(header, text="使用帮助  ?", command=self.open_help)
        help_button.pack(side="right")
        self.update_button = ttk.Button(header, text="检查更新", command=self.open_updates)
        self.update_button.pack(side="right", padx=8)
        self.step_labels = []
        steps = ttk.Frame(wrap)
        steps.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        for column, text in enumerate(("① 选曲：请载入 MIDI", "② 连接：请打开游戏", "③ 准备：确认九键界面")):
            steps.columnconfigure(column, weight=1)
            label = ttk.Label(steps, text=text, padding=(10, 7), background="#e0eeee", foreground="#567b87")
            label.grid(row=0, column=column, sticky="ew", padx=(0, 6))
            self.step_labels.append(label)
        search = ttk.LabelFrame(wrap, text="① 选一首喜欢的曲子", style="Card.TLabelframe", padding=10)
        search.grid(row=3, column=0, sticky="ew", pady=(0, 7))
        search.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(search, textvariable=self.query, font=("Microsoft YaHei UI", 12))
        self.search_entry.grid(row=0, column=0, sticky="ew", ipady=4)
        self.search_entry.bind("<Return>", lambda _: self.search(1))
        self.search_button = ttk.Button(search, text="搜索曲库", style="Accent.TButton", command=lambda: self.search(1))
        self.search_button.grid(row=0, column=1, padx=(10, 0))
        local = ttk.Button(search, text="导入 MIDI 文件", command=self.import_file)
        local.grid(row=0, column=2, padx=(8, 0))
        compatible = ttk.Button(search, text="只找能直接弹的", command=self.search_compatible)
        compatible.grid(row=0, column=3, padx=(8, 0))
        filters = ttk.Frame(search)
        filters.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        self.filter_boxes = {}
        labels = {"featured": "曲谱", "category": "分类", "format": "格式", "difficulty": "难度", "sort": "排序", "playable": "音域", "duration": "时长"}
        for column in range(4):
            filters.columnconfigure(column, weight=1, uniform="filter")
        for i, (name, choices) in enumerate(FILTER_OPTIONS.items()):
            cell = ttk.Frame(filters)
            cell.grid(row=i // 4, column=i % 4, sticky="ew", padx=(0, 8), pady=4)
            ttk.Label(cell, text=labels[name]).pack(side="left", padx=(0, 6))
            box = ttk.Combobox(cell, values=tuple(label for label, _ in choices), textvariable=self.filter_vars[name], state="readonly", width=13)
            box.pack(side="left", fill="x", expand=True)
            self.filter_boxes[name] = box
            Tooltip(box, {"featured": "全部曲谱包含所有分享；社区精选只看网站推荐。", "category": "按音乐类型筛选。选择后点击“应用筛选”。", "format": "全部格式都能浏览，自动弹奏需要 MIDI。", "difficulty": "这是网站标注的难度，不代表一定能九键演奏。", "sort": "默认最新分享；也可按下载、收藏或点赞排序。", "playable": "只想直接弹？选择“九键可直奏 · MIDI”。下载后仍会检查音符。", "duration": "按歌曲长度筛选；倍速会改变实际演奏时间。"}[name])
        actions = ttk.Frame(filters)
        actions.grid(row=1, column=3, sticky="e", pady=4)
        self.apply_button = ttk.Button(actions, text="应用筛选", command=lambda: self.search(1))
        self.apply_button.pack(side="left", padx=(0, 6))
        self.clear_button = ttk.Button(actions, text="清除筛选", command=self.clear_filters)
        self.clear_button.pack(side="left")
        catalog = ttk.Frame(wrap)
        catalog.grid(row=4, column=0, sticky="nsew")
        catalog.columnconfigure(0, weight=1)
        catalog.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(catalog, columns=("title", "author", "format", "category"), show="headings", selectmode="browse", height=3)
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
        self.load_button = ttk.Button(bar, text="载入所选曲谱", command=self.load_selected, state="disabled", style="Accent.TButton")
        self.load_button.pack(side="right")
        webpage = ttk.Button(bar, text="网页查看", command=self.open_selected)
        webpage.pack(side="right", padx=8)
        ttk.Label(wrap, textvariable=self.catalog_label, foreground="#567b87", wraplength=960).grid(row=5, column=0, sticky="w", pady=(0, 9))
        song = ttk.LabelFrame(wrap, text="当前曲谱 · 载入成功后才会演奏", style="Card.TLabelframe", padding=10)
        song.grid(row=6, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(song, textvariable=self.song_label, font=("Microsoft YaHei UI", 14, "bold"), wraplength=860).pack(anchor="w")
        ttk.Label(song, textvariable=self.details_label, foreground="#637466", wraplength=860).pack(anchor="w", pady=(5, 0))
        controls = ttk.Frame(wrap)
        controls.grid(row=7, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="② 连接游戏").grid(row=0, column=0, padx=(0, 9))
        self.window_box = ttk.Combobox(controls, textvariable=self.window_label, state="readonly")
        self.window_box.grid(row=0, column=1, sticky="ew")
        self.window_box.bind("<<ComboboxSelected>>", lambda _: self.bind_window())
        refresh = ttk.Button(controls, text="刷新窗口", command=self.refresh_windows)
        refresh.grid(row=0, column=2, padx=(8, 0))
        ttk.Label(wrap, textvariable=self.permission_label, foreground="#995d24", wraplength=960).grid(row=8, column=0, sticky="ew", pady=(5, 5))
        settings = ttk.Frame(wrap)
        settings.grid(row=9, column=0, sticky="ew", pady=(0, 8))
        armed = ttk.Checkbutton(settings, text="③ 我已进入游戏九键演奏界面", variable=self.arm_var, command=self._arm_changed)
        armed.pack(side="left")
        advanced_button = ttk.Button(settings, text="更多设置 ▾", command=self.toggle_advanced)
        advanced_button.pack(side="right")
        self.advanced = ttk.LabelFrame(wrap, text="输入设置 · 通常保持默认即可", style="Card.TLabelframe", padding=10)
        self.advanced.grid(row=10, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(self.advanced, text="单次按压（毫秒）").pack(side="left")
        self.pulse_box = ttk.Spinbox(self.advanced, from_=10, to=100, increment=5, textvariable=self.pulse, width=5)
        self.pulse_box.pack(side="left", padx=8)
        self.mode_box = ttk.Combobox(self.advanced, values=("扫描码（默认）", "虚拟键（兼容）", "Interception（需驱动）"), textvariable=self.mode, state="readonly", width=23)
        self.mode_box.pack(side="left", padx=8)
        self.mode_box.bind("<<ComboboxSelected>>", lambda _: self.bind_window())
        driver_help = ttk.Button(self.advanced, text="驱动与安装说明", command=lambda: self.open_help("没声音怎么办"))
        driver_help.pack(side="right")
        self.advanced.grid_remove()
        transport = ttk.Frame(wrap)
        transport.grid(row=11, column=0, sticky="ew")
        self.start_button = ttk.Button(transport, text="开始演奏  F8", style="Accent.TButton", command=self.toggle)
        self.start_button.pack(side="left")
        stop = ttk.Button(transport, text="停止  F9", command=self.player.stop)
        stop.pack(side="left", padx=9)
        ttk.Label(transport, text="倍速").pack(side="left", padx=(12, 6))
        self.speed_box = ttk.Combobox(transport, values=tuple(f"{v:g}×" for v in SPEEDS), textvariable=self.speed_var, state="readonly", width=8)
        self.speed_box.pack(side="left")
        self.speed_box.bind("<<ComboboxSelected>>", lambda _: self._change_speed())
        export = ttk.Button(transport, text="导出演奏记录", command=self.export_log)
        export.pack(side="right")
        self.progress = ttk.Progressbar(wrap, mode="determinate")
        self.progress.grid(row=12, column=0, sticky="ew", pady=(11, 6))
        foot = ttk.Frame(wrap)
        foot.grid(row=13, column=0, sticky="ew")
        ttk.Label(foot, textvariable=self.status_label, wraplength=720).pack(side="left")
        ttk.Label(foot, textvariable=self.time_label).pack(side="right")
        ttk.Label(wrap, text="F8 开始 / 暂停 / 继续    F9 停止    ·    切换窗口会暂停，回游戏后按 F8 继续    ·    单首结束即停止", foreground="#6e8994", font=("Microsoft YaHei UI", 9)).grid(row=14, column=0, sticky="w", pady=(9, 0))
        tips = {
            self.search_entry: "输入曲名或分享者，按回车搜索。留空可浏览全部曲谱。",
            self.search_button: "用当前关键词和筛选条件搜索第一页。",
            local: "选择电脑上的 .mid 或 .midi 文件；图片和 PDF 不能自动弹奏。",
            compatible: "一键筛选 MIDI 和九键可直奏；清空其他条件，便于找到能用的曲谱。",
            self.apply_button: "选好筛选条件后点这里；翻页会沿用这些条件。",
            self.clear_button: "清空关键词和所有筛选，回到全部曲谱第一页。",
            self.tree: "单击选中，再载入；双击可直接载入 MIDI。载入不会开始演奏。",
            self.load_button: "先下载完整 MIDI 并检查九键音域，成功后才可开始。",
            webpage: "在浏览器查看所选曲谱、试听或转谱入口。",
            self.prev: "浏览上一页，保留已应用的筛选条件。",
            self.next: "浏览下一页，保留已应用的筛选条件。",
            self.window_box: "选择已经打开的洛克王国游戏。只向这个窗口发送演奏按键。",
            refresh: "重新查找游戏窗口；刷新会先停止当前演奏。",
            armed: "先在游戏打开九键手碟界面，再勾选。每次启动工具都需要确认。",
            self.pulse_box: "一般保持 30 毫秒。它控制按多久，不改变起音节奏。",
            self.mode_box: "已配置 Interception 驱动时可选驱动模式；普通模拟输入在部分环境可能无效。",
            self.start_button: "开始前倒计时 3 秒，请切回游戏。播放中再次按 F8 暂停。",
            stop: "立即释放按键并回到曲首，不会接着播放其他歌曲。",
            self.speed_box: "1× 是原速；小于 1 为慢速，大于 1 为加速。切窗时会自动暂停。",
            export: "保存发送时间记录，便于排查节奏问题；不包含录音。",
            self.progress: "显示原谱位置；速度改变后，预计演奏时间会在曲谱卡片更新。",
            help_button: "从选曲到演奏的图文式文字指南、常见问题和更新说明。",
            self.update_button: "从项目 GitHub Releases 检查新版；不会自动安装。",
            advanced_button: "展开输入模式、单次按压时长和驱动说明。",
            driver_help: "查看没声音的排查步骤；不会安装系统驱动。",
        }
        for widget, text in tips.items():
            Tooltip(widget, text)

    def _arm_changed(self):
        if self.arm_var.get():
            self.confirmed.set()
        else:
            self.confirmed.clear()
            self.player.pause("已取消演奏界面确认，暂停发送按键。")

    def toggle_advanced(self):
        if self.advanced.winfo_ismapped():
            self.advanced.grid_remove()
        else:
            self.advanced.grid()

    def open_help(self, topic="第一次使用"):
        self.player.pause("正在查看帮助，演奏已暂停。回游戏后按 F8 继续。")
        show_help(self.root, topic)

    def search_compatible(self):
        if self.busy:
            return
        for name, choices in FILTER_OPTIONS.items():
            self.filter_vars[name].set(choices[0][0])
        self.filter_vars["format"].set("MIDI")
        self.filter_vars["playable"].set("九键可直奏 · MIDI")
        self.query.set("")
        self.search(1)

    def open_updates(self):
        self.player.pause("正在查看更新，演奏已暂停。关闭后回游戏按 F8 继续。")
        if self.update_window:
            if self.update_window.win.winfo_exists():
                self.update_window.win.lift()
            else:
                self.catalog_label.set("正在结束上次更新请求，请稍后再打开。")
            return
        self.update_window = UpdateWindow(self)

    def check_updates_background(self):
        if self.closed or self.update_checking or self.update_window:
            return
        self.update_checking = True
        channel = self.preferences["prereleases"]
        self.update_button.configure(text="正在检查更新…")
        def task():
            try:
                release, error = self.updater.check(channel), None
            except Exception as exc:
                release, error = None, exc
            self.ui_callbacks.put(lambda: done(release, error))
        def done(release, error):
            self.update_checking = False
            if error:
                self.update_button.configure(text="更新暂不可用")
            else:
                self.update_button.configure(text=f"发现新版 {release.tag}" if release else "检查更新")
            if self.update_window and self.update_window.win.winfo_exists():
                if error:
                    self.update_window.message.set(str(error))
                else:
                    self.update_window.present(release)
            # Startup checks never open dialogs, stop music or start downloads.
        threading.Thread(target=task, daemon=True, name="roco-update-check").start()

    def _clear_score(self):
        self.player.unload()
        self.song = None
        self.song_label.set("还没有可演奏的曲谱")
        self.details_label.set("载入 MIDI 后会检查九键音域；需要转换的曲谱会给出处理指引。")

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
        issue = permission_issue(chosen)
        self.permission_label.set(issue or "已连接游戏。请先打开手碟界面；切回游戏后才能发送音键。")

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
        else:
            self.catalog_label.set("先在列表中点选一首曲谱，再打开它的网页。")

    def load_selected(self):
        selection = self.tree.selection()
        if not selection or self.busy:
            return
        entry = self.entries[int(selection[0])]
        if entry.format != "midi":
            self.catalog_label.set(f"{entry.format.upper()} 曲谱不能直接演奏，请打开网页查看或转换为 MIDI 后导入。")
            return
        self._clear_score()
        self._work(f"正在下载《{entry.title}》完整 MIDI…", lambda: self.client.load(entry), self._set_score)

    def import_file(self, path=None):
        if self.busy:
            return
        self.player.pause("导入曲谱，已暂停。")
        path = path or filedialog.askopenfilename(parent=self.root, title="导入标准 MIDI 曲谱", filetypes=[("MIDI 曲谱", "*.mid *.midi")])
        if not path:
            return
        self._clear_score()
        self._work("正在解析本地 MIDI…", lambda: load_file(path), self._set_score)

    def _set_score(self, score):
        self._clear_score()
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
        if self.busy or self.update_window or (self.error_window is not None):
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
        if self.busy or self.update_window or (self.error_window is not None):
            return
        if not self.song:
            with self.player.lock:
                self.player.message = "第 1 步：请先载入一首 MIDI；想省心可点“只找能直接弹的”。"
            return
        if not self.confirmed.is_set():
            with self.player.lock:
                self.player.message = "第 3 步：进入游戏九键手碟界面后，勾选上方确认框。"
            return
        if self.player.state not in ("playing", "countdown"):
            issue = permission_issue(getattr(self.player.sink, "target", None))
            if issue:
                self.permission_label.set(issue)
                with self.player.lock:
                    self.player.message = "第 2 步：请按上方提示连接游戏窗口或处理权限。"
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
        self.player.pause("需要处理当前提示，演奏已暂停。")
        if self.error_window and self.error_window.winfo_exists():
            self.error_window.destroy()
        win = self.error_window = dialog(self.root, "曲谱小助手 · 一起解决", "680x380")
        win.grab_set()
        wrap = ttk.Frame(win, padding=22)
        wrap.pack(fill="both", expand=True)
        if isinstance(exc, UnsupportedNotes):
            title = "这首曲谱需要先转换"
            summary = f"游戏的手碟只有 9 个固定音。\n这首曲谱的 {len(exc.score.notes)} 个音符中，有 {exc.count} 个不在这 9 个音里。"
            next_step = "想马上弹奏：点下方“找能直接弹的曲谱”。\n想弹这首：查看网站转谱说明，处理后导出 MIDI，再重新导入。\n本工具保留原谱，不会自动改音或删音。"
            detail = exc.details
            self.song_label.set(f"《{exc.score.title}》暂时不能直接弹")
            self.details_label.set("请按提示换一首九键曲谱，或转换后重新导入；当前不会发送音键。")
        else:
            title = "这一步还没完成"
            if isinstance(exc, SiteBlocked):
                summary, next_step = "曲谱网站暂时拒绝了自动读取。", "本次运行已停止网站请求。可自行打开网页查看，或导入本地 MIDI。"
            elif isinstance(exc, SiteError):
                summary, next_step = "暂时无法读取在线曲谱。", "可以稍后重试、在浏览器查看原曲，或先导入本地 MIDI。"
            elif isinstance(exc, ScoreError):
                summary, next_step = "这份曲谱或当前参数无法直接使用。", "请选择标准 .mid/.midi 文件。若是重复音过密，可降低倍速；仍有问题可在网站重新导出 MIDI。"
            elif isinstance(exc, InputError):
                summary, next_step = "工具还没能连接到游戏输入。", "先确认游戏手动按 F 能响，再检查窗口和权限；点击使用帮助查看输入模式说明。"
            elif isinstance(exc, (OSError, tk.TclError)):
                summary, next_step = "文件、保存位置或输入的参数暂时不可用。", "请检查文件是否存在、磁盘权限以及按压时长（10–100 毫秒）。"
            else:
                summary, next_step = "操作遇到了问题，演奏已暂停。", "可查看下面的详细原因，并在项目 Issue 中反馈；请勿附带账号信息。"
            detail = str(exc)
        self.catalog_label.set(title + "。" + summary.replace("\n", " "))
        ttk.Label(wrap, text=title, font=("Microsoft YaHei UI", 19, "bold"), foreground="#986024").pack(anchor="w")
        ttk.Label(wrap, text=summary, wraplength=610).pack(anchor="w", pady=(14, 8))
        ttk.Label(wrap, text=next_step, wraplength=610, foreground="#567b87").pack(anchor="w", pady=(0, 10))
        details = ttk.Frame(wrap)
        show_details = tk.BooleanVar(value=False)
        def expand():
            if show_details.get():
                win.geometry("680x550")
                details.pack(fill="both", expand=True, before=buttons)
            else:
                details.pack_forget()
                win.geometry("680x380")
        ttk.Checkbutton(wrap, text="展开具体音符与技术详情" if isinstance(exc, UnsupportedNotes) else "展开详细原因", variable=show_details, command=expand).pack(anchor="w", pady=(0, 8))
        readonly_text(details, detail, height=5)
        buttons = ttk.Frame(wrap)
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
        def close():
            self.error_window = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda _: close())
        if isinstance(exc, UnsupportedNotes):
            def compatible():
                close()
                self.search_compatible()
            ttk.Button(buttons, text="找能直接弹的曲谱", style="Accent.TButton", command=compatible).pack(side="left")
            ttk.Button(buttons, text="转谱说明", command=lambda: webbrowser.open(BASE + "/guide")).pack(side="left", padx=6)
            if exc.score.source.startswith(BASE + "/scores/"):
                ttk.Button(buttons, text="原曲网页", command=lambda: webbrowser.open(exc.score.source)).pack(side="left")
        else:
            def help_for_error():
                close()
                self.open_help("没声音怎么办" if isinstance(exc, InputError) else "曲谱与筛选")
            ttk.Button(buttons, text="使用帮助", command=help_for_error).pack(side="left")
        ttk.Button(buttons, text="知道了", command=close).pack(side="right")

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                self.ui_callbacks.get_nowait()()
            except queue.Empty:
                break
        if self.closed:
            return
        if self.update_window and not self.update_window.working and not self.update_window.win.winfo_exists():
            self.update_window = None
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
        target = getattr(self.player.sink, "target", None)
        states = ((bool(self.song), "① 曲谱已就绪", "① 选曲：请载入 MIDI"),
                  (bool(target), "② 游戏已连接", "② 连接：请打开游戏"),
                  (self.confirmed.is_set(), "③ 准备就绪 · F8 开始", "③ 准备：确认九键界面"))
        for label, (ready, yes, no) in zip(self.step_labels, states):
            label.configure(text=yes if ready else no, background="#d9ece0" if ready else "#e0eeee", foreground="#28644f" if ready else "#567b87")
        self.start_button.configure(text={"playing": "暂停演奏  F8", "countdown": "取消准备  F8", "paused": "继续演奏  F8", "finished": "从头再弹  F8"}.get(s["state"], "开始演奏  F8"))
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
        if self.update_window:
            self.update_window.cancelled.set()
        if self.hotkeys:
            self.hotkeys.close()
        try:
            self.player.close()
        finally:
            self.root.destroy()


def format_time(seconds):
    seconds = max(0.0, seconds)
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"
