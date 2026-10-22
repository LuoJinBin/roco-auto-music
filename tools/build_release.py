"""Prepare ZIP and compile setup. Never starts the app or runs an installer."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rocomusic.version import VERSION
SOURCE_SHA256 = "9306fa995e1240839acc226e279a38fec9a94dac99268e8b366d5dfd85f5728c"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Prepare public release artifacts without installing or running them")
    parser.add_argument("--interception-source", required=True, type=Path)
    parser.add_argument("--iscc", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if sha(args.interception_source) != SOURCE_SHA256:
        raise SystemExit("Interception source archive does not match the recorded release source hash")
    payload = ROOT / f".vendor/release/{VERSION}/payload"
    if payload.exists():
        raise SystemExit("This version's payload directory already exists. Use a fresh version or review the existing payload before rebuilding.")
    payload.mkdir(parents=True)
    shutil.copy2(ROOT / "dist/RocoAutoMusic.exe", payload / "RocoAutoMusic.exe")
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
        shutil.copy2(ROOT / name, payload / ("使用说明.md" if name == "README.md" else name))
    for directory in ("samples", "docs", "third_party/interception"):
        for p in (ROOT / directory).rglob("*"):
            if p.is_file() and p.suffix.lower() in (".md", ".txt", ".mid", ".png"):
                target = payload / p.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
    source_target = payload / "third_party/interception/Interception-v1.0.1-source.zip"
    shutil.copy2(args.interception_source, source_target)
    licenses = payload / "third_party/runtime-licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    for path in (Path(sys.base_prefix) / "tcl").rglob("license.terms"):
        target = licenses / "TclTk" / path.relative_to(Path(sys.base_prefix) / "tcl")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for name in ("mido", "truststore", "packaging", "pyinstaller", "setuptools"):
        dist = importlib.metadata.distribution(name)
        for path in dist.files or ():
            if "license" in str(path).lower() and (".dist-info/" in str(path) or "/licenses/" in str(path)):
                original = Path(dist.locate_file(path))
                if original.is_file():
                    target = licenses / name / str(path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
    (payload / "安装前说明.txt").write_text(
        "洛克自动奏乐 " + VERSION + "（预发布）\n\n"
        "安装包仅完成构建；更新、界面、筛选与倍速未完成运行验收，未做安装/卸载实测。\n"
        "安装程序只安装本工具，不会启动奏乐、安装系统键鼠驱动或重启电脑。\n"
        "首次使用 Interception 模式需要使用者自行配置官方系统驱动；已配置过无需重复安装。\n"
        "项目自有代码采用 MIT，第三方组件适用各自许可；非商业/商业使用区别见 THIRD_PARTY_NOTICES.md。\n"
        "卸载保留个人缓存和独立安装的系统驱动。\n", encoding="utf-8-sig")
    args.output.mkdir(parents=True, exist_ok=True)
    portable = args.output / f"RocoAutoMusic-{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as z:
        for p in payload.rglob("*"):
            if p.is_file():
                z.write(p, f"RocoAutoMusic-{VERSION}/" + p.relative_to(payload).as_posix())
    shutil.copy2(args.interception_source, args.output / "Interception-v1.0.1-source.zip")
    command = [str(args.iscc.resolve()), "/Qp", f"/DPayloadDir={payload.resolve()}",
               f"/DOutputDir={args.output}", f"/DAppVersion={VERSION}", str(ROOT / "installer/RocoAutoMusic.iss")]
    subprocess.run(command, check=True)
    print("Release artifacts built. App and installers were not executed.")


if __name__ == "__main__":
    main()
