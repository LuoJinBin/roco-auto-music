"""Reproducible Windows build; never installs the system driver."""
import argparse
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=root / "dist")
args = parser.parse_args()
vendor = root / "third_party" / "interception"
if not (vendor / "x64" / "interception.dll").is_file():
    parser.error("缺少官方 x64 DLL。请先运行 python tools/fetch_interception.py；该步骤不会安装驱动。")
command = [sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--uac-admin", "--noconfirm", "--name", "RocoAutoMusic", "--copy-metadata", "mido", "--copy-metadata", "packaging", "--copy-metadata", "truststore", "--distpath", str(args.output.resolve()), "--workpath", str(root / "build"), "--specpath", str(root / "build")]
command += ["--add-binary", str(vendor / "x64" / "interception.dll") + ";third_party/interception/x64"]
for name in ("LICENSE.txt", "UPSTREAM.md"):
    command += ["--add-data", str(vendor / name) + ";third_party/interception"]
command += [str(root / "main.py")]
subprocess.run(command, cwd=root, check=True)
