"""Update UI runs network work off the Tk thread, and never resumes playback."""
from __future__ import annotations

from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from .ui import dialog, readonly_text
from .updater import DownloadCancelled, UpdateError, launch_installer_after_exit, save_preferences
from .version import RELEASES_URL, VERSION


class UpdateWindow:
    def __init__(self, app):
        self.app = app
        self.win = dialog(app.root, "王国小助手 · 检查更新", "690x580")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda _: self.close())
        self.cancelled = threading.Event()
        self.release = self.downloaded = None
        self.working = False
        wrap = ttk.Frame(self.win, padding=20)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="给小助手换上新版本", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(wrap, text=f"当前版本 {VERSION}  ·  Windows x64", foreground="#567b87").pack(anchor="w", pady=(5, 12))
        self.startup = tk.BooleanVar(value=app.preferences["check_on_start"])
        self.preview = tk.BooleanVar(value=app.preferences["prereleases"])
        ttk.Checkbutton(wrap, text="启动时检查更新（仅提醒，不自动下载）", variable=self.startup, command=self.save).pack(anchor="w")
        self.channel = ttk.Checkbutton(wrap, text="接收预发布版本（较新，可能尚未充分验证）", variable=self.preview, command=self.channel_changed)
        self.channel.pack(anchor="w", pady=(5, 10))
        self.message = tk.StringVar(value="点击“检查更新”，查看是否有新版本。")
        ttk.Label(wrap, textvariable=self.message, wraplength=620).pack(anchor="w")
        self.notes = readonly_text(wrap, "更新内容会显示在这里。\n\n安装前会征求你的确认；关闭更新窗口不会恢复演奏。", 11)
        self.progress = ttk.Progressbar(wrap, maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))
        ttk.Label(wrap, text="使用 GitHub 官方发布源 · 下载后校验 SHA-256 · 保留配置与缓存", foreground="#567b87").pack(anchor="w")
        row = ttk.Frame(wrap)
        row.pack(fill="x", pady=(14, 0))
        self.check_button = ttk.Button(row, text="检查更新", command=self.check)
        self.check_button.pack(side="left")
        ttk.Button(row, text="打开发布页", command=lambda: webbrowser.open(self.release.page if self.release else RELEASES_URL)).pack(side="left", padx=8)
        self.download_button = ttk.Button(row, text="下载新版", command=self.download, state="disabled", style="Accent.TButton")
        self.download_button.pack(side="right")
        self.cancel_button = ttk.Button(row, text="关闭", command=self.close)
        self.cancel_button.pack(side="right", padx=8)

    def save(self):
        self.app.preferences.update(check_on_start=self.startup.get(), prereleases=self.preview.get())
        try:
            save_preferences(self.app.data, self.app.preferences)
        except OSError:
            self.message.set("设置暂时无法保存。请检查磁盘权限，本次选择仍会生效。")

    def channel_changed(self):
        self.save()
        self.release = self.downloaded = None
        self.download_button.configure(state="disabled", text="下载新版", command=self.download)
        self.message.set("更新通道已更改，请重新检查。")

    def alive(self):
        return not self.app.closed and self.win.winfo_exists()

    def present(self, release):
        if not self.alive():
            return
        self.release = release
        self.downloaded = None
        text = (f"{release.tag} · {'预发布' if release.prerelease else '稳定版'}\n\n" + release.notes) if release else "这个通道暂时没有比当前版本更新的版本。\n\n你仍可以从发布页查看历史版本。"
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")
        self.message.set(f"发现新版 {release.tag} · 安装包 {release.size / 1024 / 1024:.1f} MB" if release else "当前通道没有可用更新。")
        self.download_button.configure(state="normal" if release else "disabled", text="下载新版", command=self.download)

    def _job(self, action, done):
        self.working = True
        self.check_button.configure(state="disabled")
        self.channel.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.cancel_button.configure(text="取消并关闭")
        def run():
            try:
                value = action()
                error = None
            except Exception as exc:
                value, error = None, exc
            self.app.ui_callbacks.put(lambda: finish(value, error))
        def finish(value, error):
            self.working = False
            if not self.alive():
                return
            self.check_button.configure(state="normal")
            self.channel.configure(state="normal")
            self.cancel_button.configure(text="关闭")
            if error:
                self.message.set(str(error) if isinstance(error, UpdateError) else "更新未完成，请稍后重试或打开发布页。")
                self.download_button.configure(state="normal" if self.release else "disabled")
                return
            done(value)
        threading.Thread(target=run, daemon=True, name="roco-update").start()

    def check(self):
        if self.working or self.app.update_checking:
            self.message.set("正在检查，请稍候…")
            return
        self.release = self.downloaded = None
        self.progress.configure(value=0)
        self.message.set("正在向 GitHub 查询新版本…")
        channel = self.preview.get()
        self._job(lambda: self.app.updater.check(channel), self.present)

    def download(self):
        if self.working or not self.release:
            return
        self.cancelled.clear()
        self.message.set("正在下载，请稍候；可以取消。")
        def progress(current, total):
            # Queue is drained every 80 ms, never touch Tk from a worker.
            self.app.ui_callbacks.put(lambda: self.show_progress(current, total))
        self._job(lambda: self.app.updater.download(self.release, self.cancelled, progress), self.ready)

    def show_progress(self, current, total):
        if self.alive():
            self.progress.configure(value=current / total * 100)
            self.message.set(f"正在下载 {current / 1048576:.1f} / {total / 1048576:.1f} MB")

    def ready(self, value):
        self.downloaded = value
        self.progress.configure(value=100)
        self.message.set("下载完成，SHA-256 校验通过。准备好后可退出并安装。")
        self.download_button.configure(text="退出并安装", state="normal", command=self.install)

    def install(self):
        if not self.downloaded:
            return
        if not messagebox.askyesno("退出并打开安装向导", "将停止演奏并关闭本工具，然后打开新版安装向导。\n\n配置和缓存会保留，不会安装系统驱动或重启电脑。\n便携版用户：此操作会安装新版，旧的便携文件夹仍会保留；也可从发布页下载新版 ZIP。\n\n现在继续？", parent=self.win):
            return
        self.app.player.stop()
        try:
            launch_installer_after_exit(*self.downloaded, self.app.data / "updates")
        except Exception as exc:
            self.message.set(f"未能启动安装向导：{exc}。可打开发布页手动下载。")
            return
        self.app.close()

    def close(self):
        self.cancelled.set()
        # Keep the job gated until its worker has observed cancellation.
        self.win.destroy()
        if not self.working:
            self.app.update_window = None
