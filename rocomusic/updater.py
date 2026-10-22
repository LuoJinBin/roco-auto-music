"""Public GitHub Releases updater. No credentials, driver actions or silent install."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import threading
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener

import truststore

from .version import REPOSITORY, RELEASES_URL, VERSION

MAX_INSTALLER = 250 * 1024 * 1024
VERSION_PATTERN = r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?"


class UpdateError(RuntimeError):
    pass


class DownloadCancelled(UpdateError):
    pass


def version_key(value: str):
    match = re.fullmatch(VERSION_PATTERN, value)
    if not match:
        raise UpdateError("版本号格式无法识别，请打开发布页查看。")
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch), {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage], int(number or 0))


def file_sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_preferences(directory: Path):
    defaults = {"check_on_start": False, "prereleases": "-" in VERSION}
    try:
        value = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
        if isinstance(value, dict):
            defaults.update({key: value[key] for key in defaults if type(value.get(key)) is bool})
    except (OSError, ValueError):
        pass
    return defaults


def save_preferences(directory: Path, preferences):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "settings.json"
    try:
        original = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(original, dict):
            original = {}
    except (OSError, ValueError):
        original = {}
    original.update(preferences)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class Release:
    tag: str
    notes: str
    page: str
    installer_url: str
    installer_name: str
    size: int
    checksum_url: str
    digest: str = ""
    prerelease: bool = False


def trusted_download(url):
    parsed = urlsplit(url)
    prefix = f"/{REPOSITORY}/releases/download/"
    return (parsed.scheme == "https" and parsed.hostname == "github.com"
            and parsed.path.startswith(prefix) and not parsed.username and not parsed.password
            and parsed.port in (None, 443))


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in
                ("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com")
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise UpdateError("更新下载转向了未知地址，已停止。请从项目发布页下载。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UpdateClient:
    def __init__(self, directory: Path):
        self.directory = directory
        self.blocked = ""
        self.opener = build_opener(SafeRedirect(), HTTPSHandler(context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))

    def _check_page(self, data):
        text = data[:16000].decode("utf-8", errors="ignore").lower().lstrip()
        if text.startswith(("<!doctype html", "<html")) and any(word in text for word in ("captcha", "cf-chl-", "access denied", "安全验证", "访问被拒绝")):
            self.blocked = "更新源出现安全验证或访问拒绝，本次运行已停止更新请求。请手动查看发布页。"
            raise UpdateError(self.blocked)

    def _json(self, response):
        raw = response.read(8_000_001)
        self._check_page(raw)
        if len(raw) > 8_000_000:
            raise UpdateError("版本信息过大，请手动查看发布页。")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise UpdateError("版本信息格式暂时无法识别，请稍后再试或手动查看发布页。") from None

    def _open(self, url):
        if self.blocked:
            raise UpdateError(self.blocked)
        req = Request(url, headers={"User-Agent": f"RocoAutoMusic/{VERSION}", "Accept": "application/vnd.github+json" if url.startswith("https://api.github.com/") else "application/octet-stream"})
        try:
            return self.opener.open(req, timeout=25)
        except HTTPError as exc:
            if exc.code in (401, 403, 412, 429):
                self.blocked = f"GitHub 暂时拒绝了更新请求（HTTP {exc.code}），本次运行已停止自动访问。请稍后手动查看发布页。"
                raise UpdateError(self.blocked) from exc
            raise UpdateError(f"更新服务返回 HTTP {exc.code}。请稍后再试，或手动查看发布页。") from exc
        except (URLError, OSError) as exc:
            raise UpdateError("暂时连接不上 GitHub。请检查网络，或稍后从发布页下载。") from exc

    def check(self, prereleases=False):
        # Stable endpoint is independent of how many previews were published.
        endpoint = f"https://api.github.com/repos/{REPOSITORY}/releases"
        releases = []
        if not prereleases:
            try:
                with self._open(endpoint + "/latest") as response:
                    releases = [self._json(response)]
            except UpdateError as exc:
                if isinstance(exc.__cause__, HTTPError) and exc.__cause__.code == 404:
                    return None
                raise
        else:
            for page in range(1, 11):
                with self._open(endpoint + f"?per_page=50&page={page}") as response:
                    batch = self._json(response)
                    if not isinstance(batch, list):
                        raise UpdateError("版本列表格式发生变化，请手动查看发布页。")
                    releases.extend(batch)
                    more = 'rel="next"' in response.headers.get("Link", "")
                if not more:
                    break
            else:
                raise UpdateError("版本列表超过读取上限，请手动查看发布页。")
        candidates = []
        for item in releases:
            if not isinstance(item, dict):
                raise UpdateError("发布信息格式发生变化，请手动查看发布页。")
            tag = item.get("tag_name", "")
            if item.get("draft") or (not prereleases and item.get("prerelease")) or not re.fullmatch(VERSION_PATTERN, tag):
                continue
            if not prereleases and "-" in tag:
                continue
            if version_key(tag) > version_key(VERSION):
                candidates.append(item)
        if not candidates:
            return None
        item = max(candidates, key=lambda value: version_key(value["tag_name"]))
        tag = item["tag_name"]
        name = f"RocoAutoMusic-Setup-{tag.removeprefix('v')}-x64.exe"
        assets = {a.get("name"): a for a in item.get("assets", []) if a.get("state") == "uploaded"}
        installer, checksums = assets.get(name), assets.get("SHA256SUMS.txt")
        if not installer or not checksums:
            raise UpdateError(f"发现 {tag}，但安装包或校验文件尚未发布齐全。请稍后再检查。")
        urls = [a.get("browser_download_url", "") for a in (installer, checksums)]
        if not all(trusted_download(url) and urlsplit(url).path.startswith(f"/{REPOSITORY}/releases/download/{tag}/") for url in urls):
            raise UpdateError("发布资产地址与项目版本不一致，已停止更新。")
        size = installer.get("size", 0)
        if type(size) is not int or not 0 < size <= MAX_INSTALLER:
            raise UpdateError("安装包大小异常，已停止更新。")
        digest = installer.get("digest") or ""
        if digest and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise UpdateError("发布资产的校验格式无法识别，已停止更新。")
        return Release(tag, str(item.get("body") or "此版本没有附带更新说明。")[:30000],
                       f"{RELEASES_URL}/tag/{tag}", urls[0], name, size, urls[1], digest, bool(item.get("prerelease")))

    def download(self, release: Release, cancelled: threading.Event, progress):
        if cancelled.is_set():
            raise DownloadCancelled("已取消下载。")
        with self._open(release.checksum_url) as response:
            data = response.read(128_001)
        self._check_page(data)
        if len(data) > 128_000:
            raise UpdateError("校验文件过大，已停止更新。")
        matches = []
        for line in data.decode("utf-8-sig").splitlines():
            match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line)
            if match and match[2] == release.installer_name:
                matches.append(match[1].lower())
        if len(matches) != 1:
            raise UpdateError("校验文件中没有唯一对应的安装包记录，已停止下载。")
        expected = matches[0]
        if release.digest and release.digest[7:].lower() != expected:
            raise UpdateError("GitHub 资产校验值与发布清单不一致，已停止下载。")
        if cancelled.is_set():
            raise DownloadCancelled("已取消下载。")
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / release.installer_name
        part = target.with_suffix(f".exe.{uuid.uuid4().hex}.part")
        try:
            received = 0
            digest = hashlib.sha256()
            with self._open(release.installer_url) as response, part.open("wb") as stream:
                for chunk in iter(lambda: response.read(128 * 1024), b""):
                    if received == 0:
                        self._check_page(chunk)
                    if cancelled.is_set():
                        raise DownloadCancelled("已取消下载，临时文件已清理。")
                    received += len(chunk)
                    if received > release.size or received > MAX_INSTALLER:
                        raise UpdateError("下载内容超过预期大小，已丢弃。")
                    digest.update(chunk)
                    stream.write(chunk)
                    progress(received, release.size)
            if cancelled.is_set():
                raise DownloadCancelled("已取消下载，临时文件已清理。")
            if received != release.size or digest.hexdigest() != expected:
                raise UpdateError("安装包校验失败，文件已丢弃。请稍后重新下载。")
            part.replace(target)
            return target, expected
        finally:
            part.unlink(missing_ok=True)


def launch_installer_after_exit(path: Path, expected: str, directory: Path):
    """Start a hidden waiter; it opens the interactive installer only after exit."""
    path = path.resolve()
    if not path.is_file() or file_sha256(path) != expected:
        raise UpdateError("安装前复核失败，请重新下载安装包。")
    directory.mkdir(parents=True, exist_ok=True)
    # Single-quote escaping is PowerShell escaping, never shell interpolation.
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    destination = ""
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).resolve().parent
        if (parent / "unins000.exe").is_file():
            destination = str(parent)
    args = "@('/NORESTART'" + (", " + quote('/DIR="' + destination + '"') if destination else "") + ")"
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$ownerProcess = Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue\n"
        "if ($ownerProcess) { $ownerProcess.WaitForExit() }\n"
        "Start-Sleep -Milliseconds 600\n"
        f"$installerPath = {quote(path)}\n"
        f"if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne {quote(expected)}) {{ throw 'Installer checksum mismatch' }}\n"
        f"Start-Process -FilePath $installerPath -ArgumentList {args}\n")
    # A one-shot inline command avoids changing PowerShell execution policy.
    script = "try {\n" + script + "\n} catch { Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('安装向导未能启动。请重新打开工具，在更新窗口重新下载，或从项目发布页手动安装。', '洛克自动奏乐 · 更新未完成') | Out-Null }"
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                     creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
