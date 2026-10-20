from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request

import truststore

from .score import MAX_MIDI_BYTES, Score, ScoreError, load_midi

BASE = "https://rocomusic.cn"
FILE_HOST = "c9b792ad002485adae47482f4dba6a72.r2.cloudflarestorage.com"

# Values read from the public /library filter form. Empty values mean unlimited.
FILTER_OPTIONS = {
    "featured": (("全部曲谱", ""), ("社区精选", "1")),
    "category": (("全部分类", ""), ("游戏音乐", "游戏音乐"), ("动漫音乐", "动漫音乐"), ("流行音乐", "流行音乐"), ("古典音乐", "古典音乐"), ("原创音乐", "原创音乐"), ("其他", "其他")),
    "format": (("全部格式", ""), ("MIDI", "midi"), ("图片", "image"), ("PDF", "pdf"), ("JSON", "json"), ("TXT", "txt")),
    "difficulty": (("全部难度", ""), ("入门", "easy"), ("进阶", "medium"), ("挑战", "hard")),
    "sort": (("最新分享", ""), ("下载最多", "popular"), ("收藏最多", "favorites"), ("点赞最多", "likes")),
    "playable": (("不限音域", ""), ("九键可直奏 · MIDI", "1")),
    "duration": (("不限时长", ""), ("不到 1 分钟", "short"), ("1–3 分钟", "medium"), ("超过 3 分钟", "long")),
}


def search_url(query: str = "", page: int = 1, filters: dict[str, str] | None = None) -> str:
    if not 1 <= page <= 1000 or len(query) > 100:
        raise SiteError("搜索词最多 100 字，页码范围 1–1000。")
    params = {"q": query}
    for key, value in (filters or {}).items():
        if key not in FILTER_OPTIONS or value not in {v for _, v in FILTER_OPTIONS[key]}:
            raise SiteError(f"无效的筛选条件：{key}。")
        if value:
            params[key] = value
    params["page"] = page
    return BASE + "/library?" + urlencode(params)


class SiteError(RuntimeError):
    pass


class SiteBlocked(SiteError):
    pass


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    @property
    def text(self):
        return "".join(c if isinstance(c, str) else c.text for c in self.children).strip()

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Element):
                yield from c.walk()

    def find(self, cls):
        return next((e for e in self.walk() if cls in e.attrs.get("class", "").split()), None)


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack = [self.root]
        self.skip = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if self.skip:
            return
        if tag in ("script", "style"):
            self.skip = tag
            return
        node = Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip:
                self.skip = None
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.skip:
            self.stack[-1].children.append(data)


@dataclass(frozen=True)
class Entry:
    title: str
    author: str
    url: str
    category: str = ""
    format: str = "midi"


@dataclass
class SearchResult:
    entries: list[Entry]
    page: int
    pages: int
    source: str


def parse_library(html: str, page: int, source: str) -> SearchResult:
    root = Document(html).root
    if root.find("library-search") is None:
        raise SiteError("曲库页面结构已变化，未找到搜索区域；可暂用本地 MIDI 导入。")
    items = []
    for node in root.walk():
        if node.tag != "article" or "score-card" not in node.attrs.get("class", "").split():
            continue
        title, author = node.find("score-title"), node.find("byline")
        fmt = node.find("format-chip")
        if not title or not author or not fmt or not fmt.text:
            raise SiteError("曲库卡片缺少必要字段，未把不完整结果作为成功。")
        href = title.attrs.get("href", "")
        if not re.match(r"^/scores/[0-9a-f-]{36}(?:\?|$)", href):
            raise SiteError("曲谱链接格式已变化。")
        label = node.find("score-labels")
        category = " · ".join(c.text for c in label.children if isinstance(c, Element)) if label else ""
        items.append(Entry(title.text, author.text, urljoin(BASE, href), category, fmt.text.lower()))
    pages = 1
    for n in root.walk():
        if n.attrs.get("id") == "library-page":
            pages = int(n.attrs.get("max", 1))
    return SearchResult(items, page, max(page, pages), source)


def download_link(html: str, detail_url: str) -> tuple[str, str]:
    root = Document(html).root
    panel = next((n for n in root.walk() if n.attrs.get("id") == "score-download"), None)
    if panel is None:
        raise SiteError("详情页没有曲谱下载区，页面可能已变化或曲谱已下架。")
    for n in panel.walk():
        href = n.attrs.get("href", "")
        if n.tag == "a" and re.match(r"^/api/scores/[0-9a-f-]{36}/file\?", href):
            query = parse_qs(urlparse(href).query)
            version = query.get("version", [""])[0]
            if re.fullmatch(r"[0-9a-fA-F-]{36}", version) and query.get("download") == ["1"]:
                detail_id = urlparse(detail_url).path.rstrip("/").split("/")[-1]
                if f"/scores/{detail_id}/file" not in href:
                    raise SiteError("下载链接与所选曲谱不一致。")
                return urljoin(BASE, href), version
    raise SiteError("未找到带版本的原始 MIDI 下载链接。")


def validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("rocomusic.cn", "www.rocomusic.cn") or parsed.port not in (None, 443) or parsed.username:
        raise SiteError("仅允许读取 rocomusic.cn 的 HTTPS 曲谱链接。")


class SameSiteRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_destination(req.full_url, newurl)
        if "/login" in urlparse(newurl).path:
            raise SiteBlocked("网站要求登录，已停止在线读取；请使用本地 MIDI。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_destination(origin: str, destination: str):
    """Only the observed public file endpoint may redirect to its R2 MIDI object."""
    target = urlparse(destination)
    if target.hostname in ("rocomusic.cn", "www.rocomusic.cn"):
        validate_url(destination)
        return
    original = urlparse(origin)
    if original.hostname in ("rocomusic.cn", "www.rocomusic.cn") and re.fullmatch(r"/api/scores/[0-9a-f-]{36}/file", original.path):
        if target.scheme == "https" and target.hostname == FILE_HOST and target.port in (None, 443) and not target.username and re.fullmatch(r"/rocomusic/[0-9a-f-]{36}\.mid", target.path):
            return
    raise SiteError("下载重定向超出已核实的本站 MIDI 文件存储范围。")


class CatalogClient:
    def __init__(self, cache: Path):
        self.cache = Path(cache)
        # Match Windows/browser certificate-chain verification without ignoring TLS errors.
        self.opener = build_opener(SameSiteRedirect(), HTTPSHandler(context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)))
        self.blocked = ""
        self.lock = threading.Lock()

    def _read(self, url: str, limit: int) -> bytes:
        validate_url(url)
        with self.lock:
            if self.blocked:
                raise SiteBlocked(self.blocked)
            try:
                req = Request(url, headers={"User-Agent": "RocoAutoMusic/1.0 (public MIDI reader)", "Accept": "*/*"})
                with self.opener.open(req, timeout=20) as response:
                    validate_destination(url, response.url)
                    data = response.read(limit + 1)
                if len(data) > limit:
                    raise SiteError("网站返回的文件超过大小限制。")
                if not data.startswith(b"MThd"):
                    text = data.decode("utf-8", errors="replace")
                    if any(t in text for t in ("请完成安全验证", "滑动验证", "访问被拒绝", "cf-chl-", "访问过于频繁")):
                        self.blocked = "网站出现安全验证或明确拒绝，已停止本次在线读取。可使用本地 MIDI。"
                        raise SiteBlocked(self.blocked)
                return data
            except HTTPError as exc:
                if exc.code in (401, 403, 412, 429):
                    self.blocked = f"网站返回 HTTP {exc.code}，已停止本次在线读取，不自动重试或切换通道。可使用本地 MIDI。"
                    raise SiteBlocked(self.blocked) from exc
                raise SiteError(f"网站返回 HTTP {exc.code}。") from exc
            except SiteBlocked as exc:
                self.blocked = str(exc)
                raise
            except (URLError, TimeoutError, OSError) as exc:
                raise SiteError(f"网络读取失败：{exc}。可稍后手动重试或导入本地 MIDI。") from exc

    def search(self, query: str = "", page: int = 1, filters: dict[str, str] | None = None) -> SearchResult:
        url = search_url(query, page, filters)
        return parse_library(self._read(url, 4 * 1024 * 1024).decode("utf-8"), page, url)

    def load(self, entry: Entry) -> Score:
        if entry.format != "midi":
            raise SiteError(f"当前为 {entry.format.upper()} 曲谱，自动奏乐仅支持 MIDI。可打开网页查看，或转换为 MIDI 后导入。")
        validate_url(entry.url)
        detail = self._read(entry.url, 4 * 1024 * 1024).decode("utf-8")
        url, version = download_link(detail, entry.url)
        self.cache.mkdir(parents=True, exist_ok=True)
        path = self.cache / f"{version}.mid"
        data = path.read_bytes() if path.exists() else self._read(url, MAX_MIDI_BYTES)
        score = load_midi(data, entry.title, entry.url, version)
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        metadata = {"title": entry.title, "author": entry.author, "source": entry.url, "download": url, "version": version, "sha256": score.sha256, "notes": len(score.notes), "duration": score.duration}
        path.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return score
