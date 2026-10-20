"""Optional Interception output adapter. No installation, no input interception.

The user must separately authorize and install the upstream system driver.
This module never sets a filter or receives physical key events.
"""
from __future__ import annotations

import ctypes as C
import hashlib
from pathlib import Path
import sys
import winreg

from .native import InputError, NativeSink, SCAN

DLL_SHA256 = "ab88164c11b1b48488772d4c3bfaa4509d5b0ae9dbc5a691dc4f96f0260443c8"


def driver_registered() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\keyboard", 0, winreg.KEY_READ):
            return True
    except FileNotFoundError:
        return False


class KeyStroke(C.Structure):
    _fields_ = [("code", C.c_ushort), ("state", C.c_ushort), ("information", C.c_uint)]


def library_path() -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return base / "third_party" / "interception" / "x64" / "interception.dll"


class DeviceAPI:
    def __init__(self, path: Path | None = None, _dll=None):
        self.context = None
        self.device = None
        if _dll is None:
            path = path or library_path()
            if not path.is_file():
                raise InputError("缺少 Interception 官方 x64 库。请使用完整发布包。")
            if hashlib.sha256(path.read_bytes()).hexdigest() != DLL_SHA256:
                raise InputError("Interception DLL 与已核实版本不一致，未加载。")
            self.lib = C.CDLL(str(path.resolve()))
        else:
            self.lib = _dll
        self.lib.interception_create_context.argtypes = []
        self.lib.interception_create_context.restype = C.c_void_p
        self.lib.interception_destroy_context.argtypes = [C.c_void_p]
        self.lib.interception_destroy_context.restype = None
        self.lib.interception_get_hardware_id.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_uint]
        self.lib.interception_get_hardware_id.restype = C.c_uint
        self.lib.interception_send.argtypes = [C.c_void_p, C.c_int, C.POINTER(KeyStroke), C.c_uint]
        self.lib.interception_send.restype = C.c_int

    def ensure_ready(self):
        if self.context and self.device:
            return
        self.context = self.lib.interception_create_context()
        if not self.context:
            raise InputError("Interception 驱动未就绪：需要单独批准安装官方驱动，安装后重启电脑。工具不会自动安装或重启。")
        # Test connected keyboard slots without logging or exporting hardware IDs.
        scratch = C.create_string_buffer(2048)
        for device in range(1, 11):
            if self.lib.interception_get_hardware_id(self.context, device, scratch, C.sizeof(scratch)):
                self.device = device
                return
        self.close()
        raise InputError("驱动上下文存在，但没有可用键盘设备。请检查驱动及键盘连接。")

    def send(self, up, down):
        self.ensure_ready()
        strokes = [KeyStroke(SCAN[key], 1, 0) for key in up] + [KeyStroke(SCAN[key], 0, 0) for key in down]
        if not strokes:
            return
        batch = (KeyStroke * len(strokes))(*strokes)
        sent = self.lib.interception_send(self.context, self.device, batch, len(batch))
        if sent != len(batch):
            raise InputError(f"驱动按键发送失败（{sent}/{len(batch)}），演奏已停止；没有降级重复发送。")

    def close(self):
        if self.context:
            self.lib.interception_destroy_context(self.context)
        self.context, self.device = None, None


class DeviceSink(NativeSink):
    def __init__(self, target, _api=None):
        super().__init__(target)
        self.api = _api

    def begin(self):
        super().begin()
        if self.api is None:
            self.api = DeviceAPI()
        self.api.ensure_ready()

    def _send(self, up, down):
        if not up and not down:
            return
        if self.api is None:
            raise InputError("驱动输入尚未初始化。")
        self.api.send(up, down)

    def close(self):
        try:
            self.release()
        finally:
            if self.api is not None:
                self.api.close()
                self.api = None
