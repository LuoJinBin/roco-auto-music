import argparse
import ctypes
import logging
import json
from pathlib import Path
import sys
import tkinter as tk

from rocomusic.app import App, data_directory


def main():
    parser = argparse.ArgumentParser(description="洛克王国九键自动奏乐")
    parser.add_argument("--midi", help="启动时导入本地 MIDI")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--check-driver", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_driver:
        from rocomusic.device_input import DeviceAPI, driver_registered, library_path, DLL_SHA256
        report = {"frozen": bool(getattr(sys, "frozen", False)), "registered": driver_registered(), "library_exists": library_path().is_file(), "expected_sha256": DLL_SHA256, "ready": False}
        api = None
        try:
            api = DeviceAPI()
            api.ensure_ready()
            report.update(ready=True, keyboard_slot=api.device)
        except Exception as exc:
            report["error"] = str(exc)
        finally:
            if api:
                api.close()
        Path(args.check_driver).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root, hotkeys=not args.smoke_test, initial_midi=args.midi, auto_search=not args.smoke_test)
    if args.smoke_test:
        root.after(1200, app.close)
    try:
        root.mainloop()
    finally:
        app.close()


if __name__ == "__main__":
    main()
