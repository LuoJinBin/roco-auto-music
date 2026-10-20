"""Fetch an optional upstream DLL; never install a driver or execute downloads."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import os
from pathlib import Path
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request
import zipfile

import truststore

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/oblitum/Interception/releases/download/v1.0.1/Interception.zip"
ZIP_SHA256 = "ad038963d6413055765128b0b931f6e765147c9916dba79e65d872b261f9af10"
DLL_SHA256 = "ab88164c11b1b48488772d4c3bfaa4509d5b0ae9dbc5a691dc4f96f0260443c8"
MAX_BYTES = 20 * 1024 * 1024


class HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise RuntimeError("拒绝非 HTTPS 下载重定向。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="获取已核对的 Interception v1.0.1 x64 DLL；不安装驱动")
    parser.add_argument("--archive", type=Path, help="使用已有官方 ZIP（同样检查散列），不访问网络")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("本项目的运行平台为 Windows。")
    target = ROOT / "third_party/interception/x64/interception.dll"
    if target.exists():
        if digest(target.read_bytes()) != DLL_SHA256:
            raise RuntimeError("已有 DLL 与固定版本不同，未覆盖；请保留修改后自行确认。")
        print("已存在匹配版本的 DLL；未下载、未安装驱动。")
        return
    archive = args.archive or ROOT / ".vendor/Interception-v1.0.1.zip"
    if archive.exists():
        if archive.stat().st_size > MAX_BYTES:
            raise RuntimeError("ZIP 超过大小限制。")
        data = archive.read_bytes()
    elif args.archive:
        raise RuntimeError("指定的 ZIP 不存在，未切换到网络下载。")
    else:
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        opener = build_opener(HTTPSRedirect(), HTTPSHandler(context=context))
        request = Request(URL, headers={"User-Agent": "RocoAutoMusic-source-setup/1.1"})
        with opener.open(request, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise RuntimeError("下载文件超过大小限制。")
    if digest(data) != ZIP_SHA256:
        raise RuntimeError("官方 ZIP 与固定散列不一致，已停止，未提取或执行文件。")
    with zipfile.ZipFile(BytesIO(data)) as package:
        dll = package.read("Interception/library/x64/interception.dll")
    if digest(dll) != DLL_SHA256:
        raise RuntimeError("DLL 散列不一致，已停止，未写入或执行。")
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(archive)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(dll)
    print("已获取 third_party/interception/x64/interception.dll。未安装驱动、未启动程序、未重启。")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as exc:
        raise SystemExit(f"下载返回 HTTP {exc.code}，已停止；未自动重试或切换来源。") from None
    except (OSError, URLError, RuntimeError, KeyError, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc)) from None
