"""Small, explicit Win32 boundary. No hooks into the game process or drivers."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import os
import threading

if os.name != "nt":
    raise OSError("此程序只支持 Windows。")

user32 = C.WinDLL("user32", use_last_error=True)
kernel32 = C.WinDLL("kernel32", use_last_error=True)
ULONG_PTR = C.c_size_t
LRESULT = C.c_ssize_t
WNDENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


class MOUSEINPUT(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", INPUTUNION)]


user32.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
user32.SendInput.restype = W.UINT
user32.GetForegroundWindow.restype = W.HWND
user32.GetWindowTextLengthW.argtypes = [W.HWND]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.IsWindow.argtypes = [W.HWND]
user32.IsWindowVisible.argtypes = [W.HWND]
user32.IsIconic.argtypes = [W.HWND]
user32.EnumWindows.argtypes = [WNDENUMPROC, W.LPARAM]
user32.GetAsyncKeyState.argtypes = [C.c_int]
user32.GetAsyncKeyState.restype = W.SHORT
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]

SCAN = {"B": 0x30, "F": 0x21, "G": 0x22, "H": 0x23, "J": 0x24, "K": 0x25, "T": 0x14, "Y": 0x15, "U": 0x16}


class InputError(RuntimeError):
    pass


class FocusLost(InputError):
    pass


def integrity_level(pid: int) -> int | None:
    """Read integrity only. Never changes tokens, UAC or system settings."""
    advapi = C.WinDLL("advapi32", use_last_error=True)
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    advapi.GetSidSubAuthorityCount.argtypes = [C.c_void_p]
    advapi.GetSidSubAuthorityCount.restype = C.POINTER(C.c_ubyte)
    advapi.GetSidSubAuthority.argtypes = [C.c_void_p, W.DWORD]
    advapi.GetSidSubAuthority.restype = C.POINTER(W.DWORD)
    process = kernel32.OpenProcess(0x1000, False, pid)
    token = W.HANDLE()
    if not process:
        return None
    try:
        if not advapi.OpenProcessToken(process, 8, C.byref(token)):
            return None
        length = W.DWORD()
        advapi.GetTokenInformation(token, 25, None, 0, C.byref(length))
        if not length.value:
            return None
        buf = C.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token, 25, buf, length, C.byref(length)):
            return None
        sid = C.cast(buf, C.POINTER(C.c_void_p))[0]
        count = advapi.GetSidSubAuthorityCount(sid)[0]
        return int(advapi.GetSidSubAuthority(sid, count - 1)[0])
    finally:
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


def permission_issue(target: Window | None) -> str:
    if target is None:
        return "未找到游戏窗口。请先启动游戏，再点刷新窗口。"
    own, game = integrity_level(os.getpid()), integrity_level(target.pid)
    if own is not None and game is not None and own < game:
        return "游戏以管理员权限运行，工具权限较低。请退出本工具，右键 RocoAutoMusic.exe，选择“以管理员身份运行”，由你手动确认系统提示。"
    return ""


def window_pid(hwnd: int) -> int:
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return pid.value


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    title: str
    executable: str = ""

    def foreground(self) -> bool:
        return bool(user32.IsWindow(self.hwnd) and not user32.IsIconic(self.hwnd) and user32.GetForegroundWindow() == self.hwnd and window_pid(self.hwnd) == self.pid)

    @property
    def label(self):
        return f"{self.title.strip()}  [PID {self.pid}]"


def list_windows() -> list[Window]:
    windows = []

    @WNDENUMPROC
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        text = C.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, text, len(text))
        pid = window_pid(hwnd)
        # Scope this tool to game windows, rather than offering arbitrary apps.
        if "洛克王国" not in text.value or pid == os.getpid():
            return True
        path = ""
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            try:
                size = W.DWORD(32768)
                buf = C.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, C.byref(size)):
                    path = buf.value
            finally:
                kernel32.CloseHandle(handle)
        windows.append(Window(int(hwnd), pid, text.value, path))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def physical_keys_down() -> list[str]:
    codes = {**{k: ord(k) for k in SCAN}, "Shift": 0x10, "Ctrl": 0x11, "Alt": 0x12, "Win": 0x5B, "右Win": 0x5C}
    return [name for name, vk in codes.items() if user32.GetAsyncKeyState(vk) & 0x8000]


class NativeSink:
    def __init__(self, target: Window, mode: str = "scan"):
        if mode not in ("scan", "virtual"):
            raise ValueError("unknown input mode")
        self.target = target
        self.mode = mode
        self.held: set[str] = set()
        self.lock = threading.RLock()

    def ready(self):
        return self.target.foreground()

    def begin(self):
        issue = permission_issue(self.target)
        if issue:
            raise InputError(issue)
        keys = physical_keys_down()
        if keys:
            raise InputError("请松开正在按住的按键：" + "、".join(keys))

    def _send(self, up, down):
        events = []
        scan_flag = 0x0008 if self.mode == "scan" else 0
        for key, flags in [(k, scan_flag | 0x0002) for k in up] + [(k, scan_flag) for k in down]:
            events.append(INPUT(type=1, ki=KEYBDINPUT(0 if self.mode == "scan" else ord(key), SCAN[key] if self.mode == "scan" else 0, flags, 0, 0)))
        if not events:
            return
        array = (INPUT * len(events))(*events)
        C.set_last_error(0)
        sent = user32.SendInput(len(array), array, C.sizeof(INPUT))
        if sent != len(array):
            raise InputError(f"Windows 按键发送失败（{sent}/{len(array)}，错误 {C.get_last_error()}）。请确认游戏和工具权限一致；不会自动提权。")

    def send(self, up=(), down=()):
        with self.lock:
            # Pausing already releases owned keys. Do not emit a stale key-up on resume.
            up = tuple(key for key in up if key in self.held)
            if down and not self.ready():
                raise FocusLost("游戏不在前台，已暂停。切回游戏后按 F8 继续。")
            if down and any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
                raise FocusLost("检测到修饰键，已暂停。松开按键后按 F8 继续。")
            # Keep uncertain downs in the cleanup set if SendInput partially fails.
            self.held.update(down)
            self._send(up, down)
            self.held.difference_update(up)
            self.held.update(down)

    def release(self):
        with self.lock:
            if self.held:
                self._send(tuple(sorted(self.held)), ())
                self.held.clear()

    def close(self):
        self.release()


class Hotkeys:
    """Own thread/message queue; register F8/F9 without swallowing other keys."""
    def __init__(self, toggle, stop):
        self.toggle, self.stop_callback = toggle, stop
        self.error = ""
        self.thread_id = 0
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name="roco-hotkeys", daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(3):
            self.error = "快捷键消息线程未就绪，请使用窗口按钮。"
        return self.error

    def _run(self):
        user32.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
        user32.UnregisterHotKey.argtypes = [W.HWND, C.c_int]
        user32.GetMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT]
        user32.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = W.MSG()
        user32.PeekMessageW(C.byref(msg), None, 0, 0, 0)
        registered = []
        try:
            for ident, vk in ((101, 0x77), (102, 0x78)):
                if user32.RegisterHotKey(None, ident, 0x4000, vk):
                    registered.append(ident)
                else:
                    self.error = "F8 或 F9 已被其他程序占用，请关闭占用程序后重开工具。当前可使用窗口按钮。"
                    break
            if self.error:
                for ident in registered:
                    user32.UnregisterHotKey(None, ident)
                registered.clear()
            self.ready.set()
            while user32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:
                    if msg.wParam == 101:
                        self.toggle()
                    elif msg.wParam == 102:
                        self.stop_callback()
        finally:
            for ident in registered:
                user32.UnregisterHotKey(None, ident)
            self.ready.set()

    def close(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
        if self.thread.is_alive():
            self.thread.join(2)
