"""Small, local Tk components. Original landscape artwork; no game assets."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk

BG = "#eef6f5"
INK = "#234253"
TEAL = "#267d88"


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.timer = self.popup = None
        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def schedule(self, _=None):
        self.hide()
        self.timer = self.widget.after(550, self.show)

    def show(self):
        self.timer = None
        self.popup = tk.Toplevel(self.widget)
        self.popup.overrideredirect(True)
        self.popup.attributes("-topmost", True)
        ttk.Label(self.popup, text=self.text, padding=10, wraplength=360, background="#fff9e8", foreground=INK).pack()
        self.popup.update_idletasks()
        x = min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth() - self.popup.winfo_width() - 12)
        y = min(self.widget.winfo_rooty() + self.widget.winfo_height() + 5, self.widget.winfo_screenheight() - self.popup.winfo_height() - 45)
        self.popup.geometry(f"+{max(0, x)}+{max(0, y)}")

    def hide(self, _=None):
        if self.timer:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.popup:
            self.popup.destroy()
            self.popup = None


class ScrollBody:
    def __init__(self, root):
        outer = ttk.Frame(root)
        outer.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, padding=(20, 12))
        self.item = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.item, width=e.width))
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        # Only scroll this app's body, not comboboxes, trees, dialogs or other apps.
        root.bind_all("<MouseWheel>", self.wheel, add="+")

    def wheel(self, event):
        widget = event.widget
        if widget.winfo_toplevel() is not self.canvas.winfo_toplevel():
            return
        if widget.winfo_class() in ("Treeview", "TCombobox", "Text", "Listbox", "TSpinbox"):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), "units")


class KingdomBanner(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, height=76, bg="#dceff5", highlightthickness=0)
        self.bind("<Configure>", self.paint)

    def paint(self, event):
        w, h = event.width, event.height
        self.delete("all")
        self.create_rectangle(0, 0, w, h, fill="#dceff5", outline="")
        for x, y in ((w * .55, 24), (w * .8, 16)):
            self.create_oval(x, y, x + 85, y + 22, fill="#f9ffff", outline="")
            self.create_oval(x + 17, y - 8, x + 56, y + 21, fill="#f9ffff", outline="")
        self.create_oval(w * .45, 54, w * 1.15, 175, fill="#b8d8b7", outline="")
        self.create_oval(w * .7, 64, w * 1.3, 155, fill="#8dbd9c", outline="")
        x = w - 205
        for dx, roof in ((0, 28), (28, 16), (56, 30)):
            self.create_rectangle(x + dx, roof + 12, x + dx + 22, 78, fill="#f6efd8", outline="")
            self.create_polygon(x + dx - 3, roof + 12, x + dx + 11, roof - 3, x + dx + 25, roof + 12, fill="#7c91b1", outline="")
        self.create_text(20, 27, text="洛克自动奏乐", anchor="w", font=("Microsoft YaHei UI", 23, "bold"), fill=INK)
        self.create_text(22, 61, text="把喜欢的旋律，带进王国   ·   洛克王国：世界 · 九键手碟", anchor="w", font=("Microsoft YaHei UI", 10), fill="#436d7e")
        cx, cy = w - 65, 46
        self.create_oval(cx - 32, cy - 32, cx + 32, cy + 32, fill="#f8efd2", outline="#b8a677", width=2)
        self.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, fill="#8ca6b0", outline="")
        for i in range(8):
            angle = i * math.pi / 4
            nx, ny = cx + 22 * math.cos(angle), cy + 22 * math.sin(angle)
            self.create_oval(nx - 5, ny - 5, nx + 5, ny + 5, fill="#9bb3af", outline="")


def dialog(parent, title, size="650x480"):
    win = tk.Toplevel(parent)
    win.title(title)
    win.geometry(size)
    win.minsize(520, 350)
    win.configure(bg=BG)
    win.transient(parent)
    win.update_idletasks()
    x = max(0, parent.winfo_rootx() + (parent.winfo_width() - win.winfo_width()) // 2)
    y = max(0, parent.winfo_rooty() + 60)
    win.geometry(f"+{x}+{y}")
    win.bind("<Escape>", lambda _: win.destroy())
    return win


def readonly_text(parent, text, height=10):
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, pady=(6, 10))
    box = tk.Text(frame, height=height, wrap="word", relief="flat", font=("Microsoft YaHei UI", 10), bg="#ffffff", fg=INK, padx=12, pady=10)
    scroll = ttk.Scrollbar(frame, command=box.yview)
    box.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    box.pack(side="left", fill="both", expand=True)
    box.insert("1.0", text)
    box.configure(state="disabled")
    return box


HELP = {
    "第一次使用": "① 选一首曲\n在线搜索后选中歌曲，再点“载入曲谱”；也可以导入本地 MIDI。想省心，点“只找能直接弹的”。默认列表仍显示全部。\n\n② 连接游戏\n启动《洛克王国：世界》，进入九键手碟演奏界面。在本工具中选择游戏窗口，并勾选“已进入九键演奏界面”。\n\n③ 开始演奏\n按 F8 或点击开始，3 秒内切回游戏。F8 暂停/继续，F9 停止回到开头。每首结束后停止，不自动下一首。\n\n切换到工具或其他窗口会暂停，回到游戏后要自己按 F8 继续。工具不能判断游戏当前场景，离开手碟前请先按 F9。",
    "曲谱与筛选": "游戏只有九个固定音，不是所有 MIDI 都能直接弹。\n\n“九键可直奏”只筛选网站标记的候选曲谱，载入后仍会在本机检查每个音。\n\n若提示需要转换：最省事是换一首九键可直奏曲谱；想保留这首旋律，请在网站查看转谱说明、处理后导出 MIDI，再导入本工具。转谱可能改变原曲音高；本工具不会偷偷改音或删音。\n\n图片、PDF、JSON、TXT 只能浏览，不能直接自动演奏。\n\n选择筛选后需点“应用筛选”；清除筛选会恢复所有曲谱并清空关键词。",
    "按键与倍速": "F8：首次开始有 3 秒准备时间；播放时暂停；暂停后继续。\nF9：停止并回到曲首。\n\n0.5× / 0.75× 为慢速；1× 为原速；1.25× / 1.5× / 2× 为加速。\n进度显示原谱位置，预计演奏时长随倍速变化。\n\n九键 MIDI → 游戏键：\nA2(45) → B，E3(52) → F，F3(53) → G\nG3(55) → H，A3(57) → J，B3(59) → K\nC4(60) → T，D4(62) → Y，E4(64) → U\n\n“按压时长”控制一次按多久，通常保持 30 毫秒即可，不是曲速。",
    "没声音怎么办": "先在游戏手动按 F，确认已经打开九键演奏界面。\n\n1. 检查三步指引是否都已就绪，确认选对游戏窗口。\n2. 若游戏以管理员权限运行，工具也需要相应权限。\n3. 扫描码/虚拟键是普通模拟输入，部分环境可能不接收。已配置官方 Interception 驱动的电脑可在“更多设置”选择驱动模式。\n4. 未配置驱动时，点“驱动与安装说明”了解步骤。工具不自动安装驱动、重启或修改系统安全设置。\n\n若快捷键被其他软件占用，关闭占用软件后重开本工具；也可点击开始并在 3 秒内切回游戏。\n\n“导出演奏记录”用于排查发送时间，日志不能证明游戏实际发出了声音。",
    "更新与隐私": "点右上角“检查更新”查看 GitHub Releases。无需账号，也没有自建后台。\n\n可选“启动时检查更新”，默认关闭。预发布通道提供较新的开发版本，可能存在尚未验证的问题。\n\n下载后先核对大小与 SHA-256，再由你确认退出并打开安装向导。不会静默安装，不会自动启动演奏。安装版会沿用原目录；便携版可选择安装新版，或从发布页下载新版 ZIP。\n\n旧版 1.1 没有更新按钮，需要先手动安装一次 1.2。\n\n配置和缓存保存在 %LOCALAPPDATA%\\RocoAutoMusic。更新保留此目录。程序不读游戏内存、不采集账号、不录音。\n\n本工具是玩家制作，与游戏官方和曲谱网站无隶属关系。",
}


def show_help(parent, topic="第一次使用"):
    win = dialog(parent, "奏乐指南 · 从这里开始", "700x560")
    wrap = ttk.Frame(win, padding=18)
    wrap.pack(fill="both", expand=True)
    ttk.Label(wrap, text="让第一首曲子顺利响起来", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", pady=(0, 12))
    tabs = ttk.Notebook(wrap)
    tabs.pack(fill="both", expand=True)
    for name, text in HELP.items():
        page = ttk.Frame(tabs, padding=10)
        tabs.add(page, text=name)
        readonly_text(page, text, 18)
        if name == topic:
            tabs.select(page)
    ttk.Button(wrap, text="知道了", command=win.destroy).pack(anchor="e", pady=(12, 0))
    return win
