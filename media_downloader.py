#!/usr/bin/env python3
"""
Download an accessible short-video post from a copied share message.

This tool does not crack DRM, bypass private posts, or remove a watermark from an
already-downloaded file. It extracts public playback candidates from pages/API
responses that the user can access and prefers non-watermark playback URLs.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/json;q=0.8,*/*;q=0.7"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.douyin.com/",
}

SHARE_URL_RE = re.compile(r"https?://[^\s\"'<>，。；：！？）】》、]+")
SCRIPT_RENDER_DATA_RE = re.compile(
    r'<script[^>]+id=["\']RENDER_DATA["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SCRIPT_CONTENT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
AWEME_ID_PATTERNS = (
    re.compile(r"/(?:video|note)/(\d{10,})"),
    re.compile(r"[?&](?:aweme_id|modal_id|item_ids|item_id)=(\d{10,})"),
    re.compile(r'"(?:aweme_id|awemeId|item_id|itemId)"\s*:\s*"?(\d{10,})"?'),
)
KUAISHOU_ID_PATTERNS = (
    re.compile(r"/short-video/([^/?#]+)"),
    re.compile(r"[?&](?:photoId|photo_id)=([^&#]+)"),
    re.compile(r'"(?:photoId|photo_id)"\s*:\s*"([^"]+)"'),
)
XIAOHONGSHU_ID_PATTERNS = (
    re.compile(r"/(?:explore|discovery/item)/([0-9a-zA-Z]+)"),
    re.compile(r"[?&](?:note_id|noteId|item_id)=([^&#]+)"),
    re.compile(r'"(?:noteId|note_id|itemId|item_id)"\s*:\s*"([^"]+)"'),
)
JS_STATE_MARKERS = (
    "__INITIAL_STATE__",
    "__APOLLO_STATE__",
    "__NEXT_DATA__",
    "__NUXT__",
    "__INITIAL_DATA__",
    "__INITIAL_DATA_FOR_REHYDRATION__",
)
DOUYIN_DOMAINS = ("douyin.com", "iesdouyin.com")
KUAISHOU_DOMAINS = ("kuaishou.com", "gifshow.com", "ksurl.cn", "kwai.com", "v.kuaishou.com")
XIAOHONGSHU_DOMAINS = ("xiaohongshu.com", "xhslink.com", "xhscdn.com", "xhs.cn")
PLATFORMS = ("auto", "douyin", "kuaishou", "xiaohongshu")
OUTPUT_TIME_FORMAT = "%Y%m%d_%H%M%S"
CHROMIUM_BROWSER_EXECUTABLES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
    "msedge",
    "brave-browser",
    "brave",
    "vivaldi",
    "vivaldi-stable",
    "chrome.exe",
    "msedge.exe",
    "brave.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)


class DouyinDownloadError(RuntimeError):
    """Raised when the download cannot be completed."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class Candidate:
    url: str
    source: str
    priority: int


@dataclass(frozen=True)
class ImageCandidate:
    url: str
    source: str
    priority: int


def extract_urls(text: str) -> list[str]:
    """Extract HTTP URLs from a copied share message."""
    urls: list[str] = []
    for match in SHARE_URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?)]}>\"'，。；：！？）】》、")
        if url and url not in urls:
            urls.append(url)
    return urls


def extract_aweme_id(*parts: str) -> str | None:
    """Find a Douyin aweme/video id in URLs, HTML, JSON snippets, or share text."""
    for part in parts:
        if not part:
            continue
        decoded = urllib.parse.unquote(html.unescape(part))
        for pattern in AWEME_ID_PATTERNS:
            match = pattern.search(decoded)
            if match:
                return match.group(1)
    return None


def extract_kuaishou_id(*parts: str) -> str | None:
    for part in parts:
        if not part:
            continue
        decoded = urllib.parse.unquote(html.unescape(part))
        for pattern in KUAISHOU_ID_PATTERNS:
            match = pattern.search(decoded)
            if match:
                return match.group(1)
    return None


def extract_xiaohongshu_id(*parts: str) -> str | None:
    for part in parts:
        if not part:
            continue
        decoded = urllib.parse.unquote(html.unescape(part))
        for pattern in XIAOHONGSHU_ID_PATTERNS:
            match = pattern.search(decoded)
            if match:
                return match.group(1)
    return None


def detect_platform(text: str) -> str | None:
    lowered = text.lower()
    if any(domain in lowered for domain in KUAISHOU_DOMAINS):
        return "kuaishou"
    if any(domain in lowered for domain in XIAOHONGSHU_DOMAINS):
        return "xiaohongshu"
    if any(domain in lowered for domain in DOUYIN_DOMAINS):
        return "douyin"
    return None


def normalize_cookie(cookie: str | None) -> str | None:
    """Accept either a raw cookie header or a path to a cookie text file."""
    if not cookie:
        return None
    maybe_path = Path(cookie).expanduser()
    if maybe_path.exists() and maybe_path.is_file():
        return maybe_path.read_text(encoding="utf-8").strip()
    return cookie.strip()


def build_headers(cookie: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    if extra:
        headers.update(extra)
    return headers


def http_get(
    url: str,
    *,
    cookie: str | None = None,
    timeout: float = 20.0,
    max_bytes: int | None = None,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch a URL with browser-like headers and return its final URL and body."""
    headers = build_headers(cookie, extra_headers)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if max_bytes is None:
                content = response.read()
            else:
                content = response.read(max_bytes + 1)
            return FetchResult(
                url=response.geturl(),
                status=response.status,
                content=content,
                headers={k.lower(): v for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        detail = exc.read(512).decode("utf-8", errors="replace")
        raise DouyinDownloadError(f"HTTP {exc.code} for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise DouyinDownloadError(f"Network error for {url}: {exc.reason}") from exc


def decode_text(content: bytes, headers: dict[str, str]) -> str:
    content_type = headers.get("content-type", "")
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    encoding = match.group(1) if match else "utf-8"
    try:
        return content.decode(encoding, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def load_json_bytes(content: bytes) -> Any | None:
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def extract_balanced_json_text(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text) or text[start] not in "{[":
        return None
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    stack = [closing]
    in_string = False
    quote = ""
    escaped = False

    for index in range(start + 1, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue

        if char in {"'", '"'}:
            in_string = True
            quote = char
            continue
        if char in "{[":
            stack.append("}" if char == "{" else "]")
            continue
        if char in "}]":
            if not stack or char != stack[-1]:
                return None
            stack.pop()
            if not stack:
                return text[start : index + 1]
    return None


def load_json_text(raw: str) -> Any | None:
    text = html.unescape(raw.strip())
    candidates = [text]
    try:
        candidates.append(text.encode("utf-8").decode("unicode_escape"))
    except UnicodeDecodeError:
        pass

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def extract_json_from_html(page_text: str) -> list[Any]:
    """Extract JSON payloads commonly embedded in short-video pages."""
    payloads: list[Any] = []

    for match in SCRIPT_RENDER_DATA_RE.finditer(page_text):
        raw = urllib.parse.unquote(html.unescape(match.group(1)))
        payload = load_json_text(raw)
        if payload is not None:
            payloads.append(payload)

    for match in JSON_SCRIPT_RE.finditer(page_text):
        payload = load_json_text(match.group(1))
        if payload is not None:
            payloads.append(payload)

    for match in SCRIPT_CONTENT_RE.finditer(page_text):
        script_text = html.unescape(match.group(1))
        for marker in JS_STATE_MARKERS:
            marker_index = script_text.find(marker)
            if marker_index < 0:
                continue
            equals_index = script_text.find("=", marker_index)
            search_start = equals_index + 1 if equals_index >= 0 else marker_index + len(marker)
            object_index = len(script_text)
            for opener in ("{", "["):
                index = script_text.find(opener, search_start)
                if index >= 0:
                    object_index = min(object_index, index)
            if object_index == len(script_text):
                continue
            raw_json = extract_balanced_json_text(script_text, object_index)
            if not raw_json:
                continue
            payload = load_json_text(raw_json)
            if payload is not None:
                payloads.append(payload)

    return payloads


def iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_strings(child)


def unwrap_url(url: str, *, decode_percent: bool = True) -> str:
    """Decode escaped JSON/HTML URL strings and add a scheme when needed."""
    current = (
        html.unescape(url)
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u0026", "&")
        .replace("\\u003D", "=")
        .replace("\\u003d", "=")
        .replace("\\u003F", "?")
        .replace("\\u003f", "?")
        .replace("\\/", "/")
    )
    if decode_percent:
        current = urllib.parse.unquote(current)
    if current.startswith("//"):
        current = "https:" + current
    return current


def prefer_no_watermark_url(url: str) -> str:
    """Prefer Douyin's non-watermark playback form when a watermarked URL is found."""
    url = unwrap_url(url)
    url = url.replace("/playwm/", "/play/")
    url = url.replace("playwm", "play")

    parsed = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    new_pairs = []
    for key, value in pairs:
        if key.lower() in {"watermark", "logo"} and value == "1":
            value = "0"
        new_pairs.append((key, value))
    query = urllib.parse.urlencode(new_pairs)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def looks_like_play_url(url: str) -> bool:
    lowered = url.lower()
    return (
        lowered.startswith(("http://", "https://", "//"))
        and ("douyin" in lowered or "byte" in lowered or "ixigua" in lowered)
        and any(token in lowered for token in ("/play/", "/playwm/", "aweme/v1/play", "video_id="))
    )


def looks_like_douyin_browser_video_url(url: str) -> bool:
    lowered = unwrap_url(url).lower()
    if not lowered.startswith(("http://", "https://", "//")):
        return False
    parsed = urllib.parse.urlsplit(lowered)
    host = parsed.netloc
    path = parsed.path
    if "douyinvod.com" in host:
        return "mime_type=video" in lowered or ".mp4" in path or "/video/tos/" in path
    if host.endswith("douyinstatic.com"):
        return False
    return "/video/tos/" in path and "mime_type=video" in lowered


def looks_like_kuaishou_video_url(url: str) -> bool:
    lowered = unwrap_url(url).lower()
    if not lowered.startswith(("http://", "https://", "//")):
        return False
    if not any(token in lowered for token in ("kuaishou", "gifshow", "kwai", "kwimg", "ksyuncdn")):
        return False
    return any(token in lowered for token in (".mp4", "video", "clientcachekey", "mvurl"))


def looks_like_xiaohongshu_video_url(url: str) -> bool:
    lowered = unwrap_url(url).lower()
    if not lowered.startswith(("http://", "https://", "//")):
        return False
    parsed = urllib.parse.urlsplit(lowered)
    host = parsed.netloc
    path = parsed.path
    if not path or path == "/":
        return False
    if path.endswith((".ico", ".json", ".pdf", ".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg")):
        return False
    if "sns-video" in host or "redcdn" in host:
        return ".mp4" in path or "stream" in path or "video" in path
    return ".mp4" in path and any(token in host for token in ("xiaohongshu", "xhscdn", "xhs"))


def looks_like_platform_video_url(url: str, platform: str) -> bool:
    if platform == "kuaishou":
        return looks_like_kuaishou_video_url(url)
    if platform == "xiaohongshu":
        return looks_like_xiaohongshu_video_url(url)
    return looks_like_play_url(url) or looks_like_douyin_browser_video_url(url)


def looks_like_douyin_image_url(url: str) -> bool:
    normalized = unwrap_url(url, decode_percent=False)
    lowered = normalized.lower()
    if not lowered.startswith(("http://", "https://", "//")):
        return False
    parsed = urllib.parse.urlsplit(lowered)
    if not any(token in parsed.netloc for token in ("douyinpic.com", "byteimg.com")):
        return False
    if "biz_tag=aweme_images" not in lowered and "tplv-dy-aweme-images" not in lowered:
        return False
    if "tplv-dy-water" in lowered or "water-v" in lowered:
        return False
    if "aweme_comment" in lowered or "aweme-avatar" in lowered:
        return False
    return True


def looks_like_xiaohongshu_image_url(url: str) -> bool:
    normalized = unwrap_url(url, decode_percent=False)
    lowered = normalized.lower()
    if not lowered.startswith(("http://", "https://", "//")):
        return False
    parsed = urllib.parse.urlsplit(lowered)
    host = parsed.netloc
    path = parsed.path
    if not path or path == "/":
        return False
    if "xhscdn.com" not in host and "xhscdn.net" not in host and "xiaohongshu.com" not in host:
        return False
    if not any(token in host for token in ("sns-webpic", "sns-img", "ci.xiaohongshu", "sns-avatar")):
        return False
    if "sns-avatar" in host or "/avatar/" in path:
        return False
    if "sns-webpic" not in host and "sns-img" not in host and "ci.xiaohongshu" not in host:
        return False
    if "fe-video" in host or "sns-video" in host:
        return False
    if path.endswith((".ico", ".json", ".pdf", ".js", ".css", ".svg")):
        return False
    return True


def douyin_image_key(url: str) -> str:
    parsed = urllib.parse.urlsplit(unwrap_url(url, decode_percent=False))
    return parsed.path.split("~", 1)[0]


def douyin_image_quality_score(url: str) -> int:
    lowered = unwrap_url(url, decode_percent=False).lower()
    score = 0
    if "x-signature=" not in lowered:
        score += 100
    if "tplv-dy-aweme-images" not in lowered:
        score += 50
    if ".webp" in urllib.parse.urlsplit(lowered).path:
        score += 0
    elif ".jpeg" in urllib.parse.urlsplit(lowered).path or ".jpg" in urllib.parse.urlsplit(lowered).path:
        score += 5
    else:
        score += 20
    return score


def xiaohongshu_image_key(url: str) -> str:
    parsed = urllib.parse.urlsplit(unwrap_url(url, decode_percent=False))
    filename = parsed.path.rsplit("/", 1)[-1]
    if filename:
        return filename.split("!", 1)[0]
    return parsed.path


def xiaohongshu_image_quality_score(url: str) -> int:
    lowered = unwrap_url(url, decode_percent=False).lower()
    if "nd_dft" in lowered or "dft" in lowered:
        return 0
    if "nd_wm" in lowered or "watermark" in lowered:
        return 80
    if "nd_prv" in lowered or "prv" in lowered:
        return 100
    return 50


def add_image_candidate(
    candidates_by_key: dict[str, ImageCandidate],
    url: str,
    source: str,
    order: int,
) -> None:
    normalized = unwrap_url(url, decode_percent=False)
    if not looks_like_douyin_image_url(normalized):
        return
    key = douyin_image_key(normalized)
    quality = douyin_image_quality_score(normalized)
    existing = candidates_by_key.get(key)
    if existing:
        existing_order = existing.priority // 1000
        existing_quality = existing.priority % 1000
        if quality >= existing_quality:
            return
        order = existing_order
    candidates_by_key[key] = ImageCandidate(normalized, source, order * 1000 + quality)


def add_xiaohongshu_image_candidate(
    candidates_by_key: dict[str, ImageCandidate],
    url: str,
    source: str,
    order: int,
) -> None:
    normalized = unwrap_url(url, decode_percent=False)
    if not looks_like_xiaohongshu_image_url(normalized):
        return
    key = xiaohongshu_image_key(normalized)
    quality = xiaohongshu_image_quality_score(normalized)
    existing = candidates_by_key.get(key)
    if existing:
        existing_order = existing.priority // 1000
        existing_quality = existing.priority % 1000
        if quality >= existing_quality:
            return
        order = existing_order
    candidates_by_key[key] = ImageCandidate(normalized, source, order * 1000 + quality)


def normalize_embedded_url_text(page_text: str) -> str:
    return (
        html.unescape(page_text)
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u0026", "&")
        .replace("\\u003D", "=")
        .replace("\\u003d", "=")
        .replace("\\u003F", "?")
        .replace("\\u003f", "?")
        .replace("\\/", "/")
    )


def extract_douyin_image_candidates_from_text(page_text: str, source: str = "douyin.html-image") -> list[ImageCandidate]:
    normalized_text = normalize_embedded_url_text(page_text)
    url_pattern = re.compile(r"https?://[^\"'<>\\\s]+")
    candidates_by_key: dict[str, ImageCandidate] = {}
    order = 0
    for match in url_pattern.finditer(normalized_text):
        raw_url = match.group(0).rstrip(".,;:!?)]}>\"'，。；：！？）】》、")
        if not looks_like_douyin_image_url(raw_url):
            continue
        add_image_candidate(candidates_by_key, raw_url, source, order)
        order += 1
    return sorted(candidates_by_key.values(), key=lambda candidate: candidate.priority)


def extract_xiaohongshu_image_candidates_from_text(
    page_text: str,
    source: str = "xiaohongshu.html-image",
) -> list[ImageCandidate]:
    normalized_text = normalize_embedded_url_text(page_text)
    url_pattern = re.compile(r"https?://[^\"'<>\\\s]+")
    candidates_by_key: dict[str, ImageCandidate] = {}
    order = 0
    for match in url_pattern.finditer(normalized_text):
        raw_url = match.group(0).rstrip(".,;:!?)]}>\"'，。；：！？）】》、")
        if not looks_like_xiaohongshu_image_url(raw_url):
            continue
        add_xiaohongshu_image_candidate(candidates_by_key, raw_url, source, order)
        order += 1
    return sorted(candidates_by_key.values(), key=lambda candidate: candidate.priority)


def add_candidate(
    candidates: list[Candidate],
    seen: set[str],
    url: str,
    source: str,
    priority: int,
) -> None:
    normalized = prefer_no_watermark_url(url)
    if not looks_like_play_url(normalized):
        return
    if normalized in seen:
        return
    seen.add(normalized)
    candidates.append(Candidate(normalized, source, priority))


def add_platform_candidate(
    candidates: list[Candidate],
    seen: set[str],
    url: str,
    source: str,
    priority: int,
    platform: str,
) -> None:
    normalized = unwrap_url(url)
    if not looks_like_platform_video_url(normalized, platform):
        return
    if normalized in seen:
        return
    seen.add(normalized)
    candidates.append(Candidate(normalized, source, priority))


def extract_candidates_from_json(value: Any) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    preferred_addr_keys = {
        "play_addr": 10,
        "play_addr_h264": 12,
        "download_addr": 30,
        "play_api": 20,
    }

    for item in iter_dicts(value):
        for key, priority in preferred_addr_keys.items():
            addr = item.get(key)
            if not isinstance(addr, dict):
                continue
            urls = addr.get("url_list")
            if isinstance(urls, list):
                for raw_url in urls:
                    if isinstance(raw_url, str):
                        add_candidate(candidates, seen, raw_url, key, priority)
            uri = addr.get("uri")
            if isinstance(uri, str) and uri.startswith(("http://", "https://", "//")):
                add_candidate(candidates, seen, uri, key, priority + 5)

        bit_rates = item.get("bit_rate")
        if isinstance(bit_rates, list):
            for index, bit_rate in enumerate(bit_rates):
                if not isinstance(bit_rate, dict):
                    continue
                addr = bit_rate.get("play_addr") or bit_rate.get("play_addr_h264")
                if not isinstance(addr, dict):
                    continue
                urls = addr.get("url_list")
                if isinstance(urls, list):
                    for raw_url in urls:
                        if isinstance(raw_url, str):
                            add_candidate(
                                candidates,
                                seen,
                                raw_url,
                                f"bit_rate[{index}]",
                                5 + index,
                            )

    for raw_url in iter_strings(value):
        if looks_like_play_url(unwrap_url(raw_url)):
            add_candidate(candidates, seen, raw_url, "json-string", 50)

    return sorted(candidates, key=lambda candidate: candidate.priority)


def add_urls_from_value(
    candidates: list[Candidate],
    seen: set[str],
    value: Any,
    source: str,
    priority: int,
    platform: str,
) -> None:
    if isinstance(value, str):
        add_platform_candidate(candidates, seen, value, source, priority, platform)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            add_urls_from_value(candidates, seen, child, f"{source}[{index}]", priority + index, platform)
    elif isinstance(value, dict):
        for key in ("url", "masterUrl", "backupUrl", "playUrl", "videoUrl", "src"):
            if key in value:
                add_urls_from_value(candidates, seen, value[key], f"{source}.{key}", priority, platform)
        for key in ("urls", "urlList", "backupUrls", "mainMvUrls"):
            if key in value:
                add_urls_from_value(candidates, seen, value[key], f"{source}.{key}", priority + 5, platform)


def extract_kuaishou_candidates_from_json(value: Any) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    preferred_keys = {
        "mainMvUrls": 5,
        "photoUrl": 10,
        "photoH264Url": 8,
        "photoH265Url": 12,
        "playUrl": 15,
        "videoUrl": 20,
        "h264Url": 8,
        "h265Url": 12,
        "url": 80,
    }
    for item in iter_dicts(value):
        for key, priority in preferred_keys.items():
            if key in item:
                add_urls_from_value(candidates, seen, item[key], f"kuaishou.{key}", priority, "kuaishou")

    for raw_url in iter_strings(value):
        if looks_like_kuaishou_video_url(raw_url):
            add_platform_candidate(candidates, seen, raw_url, "kuaishou.json-string", 90, "kuaishou")

    return sorted(candidates, key=lambda candidate: candidate.priority)


def extract_xiaohongshu_candidates_from_json(value: Any) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for item in iter_dicts(value):
        stream = item.get("stream")
        if isinstance(stream, dict):
            for codec_index, codec in enumerate(("h264", "h265", "av1")):
                streams = stream.get(codec)
                if isinstance(streams, list):
                    for stream_index, stream_item in enumerate(streams):
                        add_urls_from_value(
                            candidates,
                            seen,
                            stream_item,
                            f"xiaohongshu.stream.{codec}[{stream_index}]",
                            5 + codec_index * 10 + stream_index,
                            "xiaohongshu",
                        )

        for key, priority in (
            ("masterUrl", 8),
            ("backupUrls", 12),
            ("videoUrl", 20),
            ("video_url", 20),
            ("playUrl", 25),
            ("url", 90),
        ):
            if key in item:
                add_urls_from_value(candidates, seen, item[key], f"xiaohongshu.{key}", priority, "xiaohongshu")

    for raw_url in iter_strings(value):
        if looks_like_xiaohongshu_video_url(raw_url):
            add_platform_candidate(candidates, seen, raw_url, "xiaohongshu.json-string", 100, "xiaohongshu")

    return sorted(candidates, key=lambda candidate: candidate.priority)


def extract_platform_candidates_from_html(page_text: str, platform: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    if platform == "kuaishou":
        extractor = extract_kuaishou_candidates_from_json
    elif platform == "xiaohongshu":
        extractor = extract_xiaohongshu_candidates_from_json
    else:
        extractor = extract_candidates_from_json

    for payload in extract_json_from_html(page_text):
        for candidate in extractor(payload):
            add_platform_candidate(candidates, seen, candidate.url, candidate.source, candidate.priority, platform)

    url_pattern = re.compile(r"https?:\\?/\\?/[^\"'<>\\\s]+|https?://[^\"'<>\\\s]+|//[^\"'<>\\\s]+")
    for match in url_pattern.finditer(page_text):
        raw_url = match.group(0)
        if looks_like_platform_video_url(raw_url, platform):
            add_platform_candidate(candidates, seen, raw_url, f"{platform}.html-url", 120, platform)

    return sorted(candidates, key=lambda candidate: candidate.priority)


def extract_candidates_from_html(page_text: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for payload in extract_json_from_html(page_text):
        for candidate in extract_candidates_from_json(payload):
            add_candidate(candidates, seen, candidate.url, candidate.source, candidate.priority)

    # Fallback for escaped URLs outside application/json script tags.
    url_pattern = re.compile(r"https?:\\?/\\?/[^\"'<>\\\s]+|https?://[^\"'<>\\\s]+")
    for match in url_pattern.finditer(page_text):
        raw_url = match.group(0)
        if looks_like_play_url(unwrap_url(raw_url)):
            add_candidate(candidates, seen, raw_url, "html-url", 60)

    return sorted(candidates, key=lambda candidate: candidate.priority)


def find_chrome_executable(chrome_path: str | None = None) -> str | None:
    if chrome_path:
        expanded = Path(chrome_path).expanduser()
        if expanded.exists():
            return str(expanded)
        return shutil.which(chrome_path)
    for executable in CHROMIUM_BROWSER_EXECUTABLES:
        executable_path = Path(executable).expanduser()
        if executable_path.exists():
            return str(executable_path)
        found = shutil.which(executable)
        if found:
            return found
    return None


def browser_fallback_was_unavailable(logs: Iterable[str]) -> bool:
    return any("Browser fallback skipped:" in line for line in logs)


def iter_netlog_urls(payload: Any) -> Iterable[str]:
    url_pattern = re.compile(r"https?://[^\s\"'<>\\]+")
    for value in iter_strings(payload):
        if value.startswith(("http://", "https://")):
            yield value
            continue
        for match in url_pattern.finditer(value):
            yield match.group(0)


def browser_candidate_priority(url: str, platform: str, index: int) -> int:
    if platform == "douyin":
        parsed = urllib.parse.urlsplit(unwrap_url(url))
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("bt", "br"):
            raw_value = (query.get(key) or [""])[0]
            try:
                value = int(raw_value)
            except ValueError:
                continue
            if value > 0:
                return max(1, 1_000_000 - min(value, 999_999))
    return 5_000_000 + index


def extract_browser_candidates_from_netlog_payload(payload: Any, platform: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for index, raw_url in enumerate(iter_netlog_urls(payload)):
        if looks_like_platform_video_url(raw_url, platform):
            add_platform_candidate(
                candidates,
                seen,
                raw_url,
                f"{platform}.browser-netlog",
                browser_candidate_priority(raw_url, platform, index),
                platform,
            )
    return sorted(candidates, key=lambda candidate: candidate.priority)


def gather_browser_candidates(
    share_text: str,
    *,
    platform: str,
    cookie: str | None = None,
    timeout: float = 12.0,
    chrome_path: str | None = None,
) -> tuple[str | None, list[Candidate], list[ImageCandidate], list[str]]:
    urls = extract_urls(share_text)
    if not urls:
        if share_text.strip().startswith(("http://", "https://")):
            urls = [share_text.strip()]
        else:
            raise DouyinDownloadError("No URL found in the share text.")

    logs: list[str] = []
    chrome = find_chrome_executable(chrome_path)
    if not chrome:
        logs.append(
            "Browser fallback skipped: no Chromium-compatible browser was found. "
            "Install Chrome, Chromium, Edge, Brave, or pass --chrome-path."
        )
        return extract_platform_id(platform, share_text), [], [], logs
    if cookie:
        logs.append("Browser fallback uses a fresh local Chrome profile; --cookie only applies to direct HTTP parsing.")

    item_id = extract_platform_id(platform, share_text)
    candidates: list[Candidate] = []
    image_candidates: list[ImageCandidate] = []
    seen_image_urls: set[str] = set()
    seen: set[str] = set()
    target_urls: list[str] = []

    for share_url in urls:
        try:
            resolved = http_get(
                share_url,
                cookie=cookie,
                timeout=min(timeout, 20.0),
                max_bytes=256 * 1024,
                extra_headers={"Referer": platform_referer(platform)},
            )
            page_text = decode_text(resolved.content, resolved.headers)
            item_id = item_id or extract_platform_id(platform, resolved.url, page_text)
            if resolved.url not in target_urls:
                target_urls.append(resolved.url)
        except DouyinDownloadError as exc:
            logs.append(f"{platform}: browser fallback pre-resolve failed: {exc}")
        if share_url not in target_urls:
            target_urls.append(share_url)

    for target_url in target_urls:
        with tempfile.TemporaryDirectory(prefix="media_downloader_chrome_", ignore_cleanup_errors=True) as tmpdir:
            netlog_path = Path(tmpdir) / "netlog.json"
            command = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--mute-audio",
                "--autoplay-policy=no-user-gesture-required",
                f"--user-data-dir={tmpdir}",
                f"--log-net-log={netlog_path}",
                "--net-log-capture-mode=IncludeSensitive",
                f"--virtual-time-budget={max(1000, int(timeout * 1000))}",
                "--dump-dom",
                target_url,
            ]
            logs.append(f"{platform}: browser fallback opening {target_url}")
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 10,
                )
            except subprocess.TimeoutExpired:
                logs.append(f"{platform}: browser fallback timed out after {timeout:.1f}s")
                continue
            except OSError as exc:
                logs.append(f"{platform}: browser fallback failed to start Chrome: {exc}")
                continue

            if completed.returncode != 0:
                stderr_line = completed.stderr.strip().splitlines()
                detail = f": {stderr_line[0]}" if stderr_line else ""
                logs.append(f"{platform}: browser fallback Chrome exited with {completed.returncode}{detail}")

            item_id = item_id or extract_platform_id(platform, target_url, completed.stdout)
            if platform in {"douyin", "xiaohongshu"}:
                image_extractor = (
                    extract_douyin_image_candidates_from_text
                    if platform == "douyin"
                    else extract_xiaohongshu_image_candidates_from_text
                )
                dom_image_candidates = image_extractor(
                    completed.stdout,
                    f"{platform}.browser-dom-image",
                )
                logs.append(f"{platform}: browser fallback found {len(dom_image_candidates)} image candidate(s)")
                for candidate in dom_image_candidates:
                    if candidate.url in seen_image_urls:
                        continue
                    seen_image_urls.add(candidate.url)
                    image_candidates.append(candidate)

            for candidate in extract_platform_candidates_from_html(completed.stdout, platform):
                add_platform_candidate(
                    candidates,
                    seen,
                    candidate.url,
                    f"{candidate.source}:browser-dom",
                    candidate.priority + 2_000_000,
                    platform,
                )

            if not netlog_path.exists():
                logs.append(f"{platform}: browser fallback produced no network log")
                continue
            try:
                payload = json.loads(netlog_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logs.append(f"{platform}: browser fallback could not parse network log: {exc}")
                continue

            netlog_candidates = extract_browser_candidates_from_netlog_payload(payload, platform)
            logs.append(f"{platform}: browser fallback found {len(netlog_candidates)} network video candidate(s)")
            for candidate in netlog_candidates:
                add_platform_candidate(candidates, seen, candidate.url, candidate.source, candidate.priority, platform)
            if candidates or image_candidates:
                break

    return (
        item_id,
        sorted(candidates, key=lambda candidate: candidate.priority),
        sorted(image_candidates, key=lambda candidate: candidate.priority),
        logs,
    )


def detail_api_urls(aweme_id: str) -> list[str]:
    encoded = urllib.parse.quote(aweme_id)
    return [
        f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={encoded}",
        (
            "https://www.douyin.com/aweme/v1/web/aweme/detail/"
            f"?aweme_id={encoded}&aid=6383&device_platform=webapp"
        ),
    ]


def gather_candidates(
    share_text: str,
    *,
    cookie: str | None = None,
    timeout: float = 20.0,
) -> tuple[str | None, list[Candidate], list[ImageCandidate], list[str]]:
    """Resolve a share message and gather candidate video URLs."""
    urls = extract_urls(share_text)
    if not urls:
        if share_text.strip().startswith(("http://", "https://")):
            urls = [share_text.strip()]
        else:
            raise DouyinDownloadError("No URL found in the share text.")

    logs: list[str] = []
    all_candidates: list[Candidate] = []
    image_candidates: list[ImageCandidate] = []
    seen_image_urls: set[str] = set()
    seen_candidates: set[str] = set()
    aweme_id = extract_aweme_id(share_text)

    for share_url in urls:
        logs.append(f"Resolving {share_url}")
        resolved = http_get(share_url, cookie=cookie, timeout=timeout, max_bytes=4 * 1024 * 1024)
        page_text = decode_text(resolved.content, resolved.headers)
        logs.append(f"Final URL: {resolved.url}")
        aweme_id = aweme_id or extract_aweme_id(resolved.url, page_text)

        for candidate in extract_candidates_from_html(page_text):
            add_candidate(all_candidates, seen_candidates, candidate.url, candidate.source, candidate.priority)
        for image_candidate in extract_douyin_image_candidates_from_text(page_text):
            if image_candidate.url in seen_image_urls:
                continue
            seen_image_urls.add(image_candidate.url)
            image_candidates.append(image_candidate)

    if aweme_id:
        for api_url in detail_api_urls(aweme_id):
            try:
                logs.append(f"Fetching detail API: {api_url}")
                result = http_get(api_url, cookie=cookie, timeout=timeout, max_bytes=8 * 1024 * 1024)
            except DouyinDownloadError as exc:
                logs.append(str(exc))
                continue

            payload = load_json_bytes(result.content)
            if payload is None:
                logs.append(f"Detail API returned non-JSON: {result.url}")
                continue
            if isinstance(payload, dict):
                status_code = payload.get("status_code")
                status_msg = payload.get("status_msg")
                if status_code not in (None, 0):
                    logs.append(f"Detail API returned status_code={status_code}: {status_msg or '<no message>'}")

            for candidate in extract_candidates_from_json(payload):
                add_candidate(all_candidates, seen_candidates, candidate.url, candidate.source, candidate.priority)

    return (
        aweme_id,
        sorted(all_candidates, key=lambda candidate: candidate.priority),
        sorted(image_candidates, key=lambda candidate: candidate.priority),
        logs,
    )


def platform_referer(platform: str) -> str:
    return {
        "douyin": "https://www.douyin.com/",
        "kuaishou": "https://www.kuaishou.com/",
        "xiaohongshu": "https://www.xiaohongshu.com/",
    }.get(platform, "https://www.douyin.com/")


def extract_platform_id(platform: str, *parts: str) -> str | None:
    if platform == "kuaishou":
        return extract_kuaishou_id(*parts)
    if platform == "xiaohongshu":
        return extract_xiaohongshu_id(*parts)
    return extract_aweme_id(*parts)


def gather_web_platform_candidates(
    share_text: str,
    *,
    platform: str,
    cookie: str | None = None,
    timeout: float = 20.0,
) -> tuple[str | None, list[Candidate], list[ImageCandidate], list[str]]:
    urls = extract_urls(share_text)
    if not urls:
        if share_text.strip().startswith(("http://", "https://")):
            urls = [share_text.strip()]
        else:
            raise DouyinDownloadError("No URL found in the share text.")

    logs: list[str] = []
    all_candidates: list[Candidate] = []
    image_candidates: list[ImageCandidate] = []
    seen_image_urls: set[str] = set()
    seen_candidates: set[str] = set()
    item_id = extract_platform_id(platform, share_text)
    headers = {
        "Referer": platform_referer(platform),
        "Origin": platform_referer(platform).rstrip("/"),
    }

    for share_url in urls:
        logs.append(f"{platform}: resolving {share_url}")
        resolved = http_get(
            share_url,
            cookie=cookie,
            timeout=timeout,
            max_bytes=6 * 1024 * 1024,
            extra_headers=headers,
        )
        page_text = decode_text(resolved.content, resolved.headers)
        logs.append(f"{platform}: final URL: {resolved.url}")
        item_id = item_id or extract_platform_id(platform, resolved.url, page_text)

        for candidate in extract_platform_candidates_from_html(page_text, platform):
            add_platform_candidate(
                all_candidates,
                seen_candidates,
                candidate.url,
                candidate.source,
                candidate.priority,
                platform,
            )
        if platform == "xiaohongshu":
            for image_candidate in extract_xiaohongshu_image_candidates_from_text(page_text):
                if image_candidate.url in seen_image_urls:
                    continue
                seen_image_urls.add(image_candidate.url)
                image_candidates.append(image_candidate)

    return (
        item_id,
        sorted(all_candidates, key=lambda candidate: candidate.priority),
        sorted(image_candidates, key=lambda candidate: candidate.priority),
        logs,
    )


def gather_candidates_for_request(
    share_text: str,
    *,
    platform: str,
    cookie: str | None = None,
    timeout: float = 20.0,
    browser_fallback: bool = True,
    browser_timeout: float = 12.0,
    chrome_path: str | None = None,
) -> tuple[str, str | None, list[Candidate], list[ImageCandidate], list[str]]:
    resolved_platform = detect_platform(share_text) if platform == "auto" else platform
    if not resolved_platform:
        raise DouyinDownloadError(
            "Cannot detect platform from the share text. Pass --platform douyin, "
            "--platform kuaishou, or --platform xiaohongshu."
        )

    if resolved_platform == "douyin":
        item_id, candidates, image_candidates, logs = gather_candidates(share_text, cookie=cookie, timeout=timeout)
        if not candidates and not image_candidates and browser_fallback:
            logs.append("douyin: direct extraction found no candidates, trying browser fallback")
            browser_item_id, browser_candidates, browser_image_candidates, browser_logs = gather_browser_candidates(
                share_text,
                platform=resolved_platform,
                cookie=cookie,
                timeout=browser_timeout,
                chrome_path=chrome_path,
            )
            logs.extend(browser_logs)
            item_id = item_id or browser_item_id
            candidates = browser_candidates
            image_candidates = browser_image_candidates
        return resolved_platform, item_id, candidates, image_candidates, logs

    if resolved_platform in {"kuaishou", "xiaohongshu"}:
        item_id, candidates, image_candidates, platform_logs = gather_web_platform_candidates(
            share_text,
            platform=resolved_platform,
            cookie=cookie,
            timeout=timeout,
        )
        if not candidates and not image_candidates and browser_fallback:
            platform_logs.append(f"{resolved_platform}: direct extraction found no candidates, trying browser fallback")
            browser_item_id, browser_candidates, browser_image_candidates, browser_logs = gather_browser_candidates(
                share_text,
                platform=resolved_platform,
                cookie=cookie,
                timeout=browser_timeout,
                chrome_path=chrome_path,
            )
            platform_logs.extend(browser_logs)
            item_id = item_id or browser_item_id
            candidates = browser_candidates
            image_candidates = browser_image_candidates
        return resolved_platform, item_id, candidates, image_candidates, platform_logs

    raise DouyinDownloadError(f"Unsupported platform: {resolved_platform}")


def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 1000):
        candidate = parent / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise DouyinDownloadError(f"Cannot find a free output filename near {path}")


def timestamp_output_name() -> str:
    return f"{time.strftime(OUTPUT_TIME_FORMAT)}.mp4"


def timestamp_output_stem() -> str:
    return time.strftime(OUTPUT_TIME_FORMAT)


def content_type_is_video(headers: dict[str, str]) -> bool:
    content_type = headers.get("content-type", "").lower()
    if not content_type:
        return True
    return content_type.startswith("video/") or "octet-stream" in content_type


def content_type_is_image(headers: dict[str, str]) -> bool:
    content_type = headers.get("content-type", "").lower()
    if not content_type:
        return True
    return content_type.startswith("image/") or "octet-stream" in content_type


def image_suffix_from_url(url: str) -> str:
    path = urllib.parse.urlsplit(unwrap_url(url, decode_percent=False)).path.lower()
    for suffix in (".webp", ".jpg", ".jpeg", ".png", ".avif", ".gif"):
        if suffix in path:
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def image_suffix_from_content_type(content_type: str | None, fallback: str) -> str:
    lowered = (content_type or "").lower().split(";", 1)[0].strip()
    return {
        "image/webp": ".webp",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/avif": ".avif",
        "image/gif": ".gif",
    }.get(lowered, fallback)


def download_candidate(
    candidate: Candidate,
    output_path: Path,
    *,
    cookie: str | None = None,
    timeout: float = 30.0,
    referer: str | None = None,
) -> Path:
    headers = build_headers(
        cookie,
        {
            "Accept": "*/*",
            "Referer": referer or "https://www.douyin.com/",
        },
    )
    request = urllib.request.Request(candidate.url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            if not content_type_is_video(response_headers):
                content_type = response_headers.get("content-type", "unknown")
                raise DouyinDownloadError(
                    f"Candidate returned non-video content ({content_type}) from {candidate.source}"
                )

            tmp_path = output_path.with_suffix(output_path.suffix + ".part")
            with tmp_path.open("wb") as fp:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    fp.write(chunk)
            tmp_path.replace(output_path)
            return output_path
    except urllib.error.HTTPError as exc:
        raise DouyinDownloadError(f"HTTP {exc.code} while downloading {candidate.url}") from exc
    except urllib.error.URLError as exc:
        raise DouyinDownloadError(f"Network error while downloading {candidate.url}: {exc.reason}") from exc


def download_image_candidate(
    candidate: ImageCandidate,
    output_path: Path,
    *,
    cookie: str | None = None,
    timeout: float = 30.0,
    referer: str | None = None,
) -> Path:
    headers = build_headers(
        cookie,
        {
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": referer or "https://www.douyin.com/",
        },
    )
    request = urllib.request.Request(candidate.url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_headers = {k.lower(): v for k, v in response.headers.items()}
            if not content_type_is_image(response_headers):
                content_type = response_headers.get("content-type", "unknown")
                raise DouyinDownloadError(
                    f"Candidate returned non-image content ({content_type}) from {candidate.source}"
                )

            suffix = image_suffix_from_content_type(
                response_headers.get("content-type"),
                output_path.suffix or image_suffix_from_url(candidate.url),
            )
            if output_path.suffix.lower() != suffix:
                output_path = output_path.with_suffix(suffix)
            tmp_path = output_path.with_suffix(output_path.suffix + ".part")
            with tmp_path.open("wb") as fp:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    fp.write(chunk)
            tmp_path.replace(output_path)
            return output_path
    except urllib.error.HTTPError as exc:
        raise DouyinDownloadError(f"HTTP {exc.code} while downloading image {candidate.url}") from exc
    except urllib.error.URLError as exc:
        raise DouyinDownloadError(f"Network error while downloading image {candidate.url}: {exc.reason}") from exc


def download_image_candidates(
    candidates: list[ImageCandidate],
    output_dir: Path,
    *,
    output_name: str | None = None,
    overwrite: bool = False,
    cookie: str | None = None,
    timeout: float = 30.0,
    referer: str | None = None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = Path(output_name).stem if output_name else timestamp_output_stem()
    saved_paths: list[Path] = []
    multiple = len(candidates) > 1
    for index, candidate in enumerate(candidates, start=1):
        suffix = image_suffix_from_url(candidate.url)
        filename = f"{base_name}_{index:02d}{suffix}" if multiple else f"{base_name}{suffix}"
        output_path = output_dir / filename
        if output_path.exists() and not overwrite:
            output_path = unique_output_path(output_path)
        saved_paths.append(
            download_image_candidate(
                candidate,
                output_path,
                cookie=cookie,
                timeout=timeout,
                referer=referer,
            )
        )
    return saved_paths


def save_metadata(
    path: Path,
    platform: str,
    item_id: str | None,
    candidates: list[Candidate],
    image_candidates: list[ImageCandidate] | None,
    logs: list[str],
) -> None:
    metadata = {
        "platform": platform,
        "item_id": item_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "candidates": [candidate.__dict__ for candidate in candidates],
        "image_candidates": [candidate.__dict__ for candidate in (image_candidates or [])],
        "logs": logs,
    }
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")


def probe_media_info(path: Path) -> dict[str, Any]:
    """Return basic video metadata using ffprobe when available."""
    info: dict[str, Any] = {"file_size": path.stat().st_size}
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        info["warning"] = "ffprobe is not installed; only file size is available."
        return info

    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name,bit_rate,duration",
        "-show_entries",
        "format=size,duration,bit_rate",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        info["warning"] = completed.stderr.strip() or "ffprobe failed."
        return info

    payload = json.loads(completed.stdout)
    stream = (payload.get("streams") or [{}])[0]
    fmt = payload.get("format") or {}
    info.update(
        {
            "codec": stream.get("codec_name"),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "duration": stream.get("duration") or fmt.get("duration"),
            "video_bit_rate": stream.get("bit_rate"),
            "format_bit_rate": fmt.get("bit_rate"),
        }
    )
    return info


def print_media_info(path: Path) -> None:
    info = probe_media_info(path)
    print(f"file: {path}")
    if info.get("width") and info.get("height"):
        print(f"resolution: {info['width']}x{info['height']}")
    if info.get("codec"):
        print(f"codec: {info['codec']}")
    if info.get("duration"):
        print(f"duration: {float(info['duration']):.2f}s")
    if info.get("file_size") is not None:
        print(f"size: {int(info['file_size']) / 1024 / 1024:.2f} MiB ({info['file_size']} bytes)")
    if info.get("format_bit_rate"):
        print(f"bitrate: {int(info['format_bit_rate']) / 1000:.0f} kbps")
    if info.get("warning"):
        print(f"warning: {info['warning']}", file=sys.stderr)


def make_x_compatible_if_needed(path: Path, args: argparse.Namespace) -> Path | None:
    """Create an X-compatible copy when the downloaded video is not upload-friendly."""
    try:
        import x_transcoder
    except ImportError as exc:
        raise DouyinDownloadError("x_transcoder.py is required for --x-compatible.") from exc

    options = x_transcoder.default_options(
        overwrite=args.x_overwrite,
        crf=args.x_crf,
        verbose=args.verbose,
    )
    info = x_transcoder.probe_media(path)
    compatibility = x_transcoder.check_with_options(info, options)
    if compatibility.ok and not args.x_force:
        print("x_compatible: yes")
        return path

    if compatibility.ok and args.x_force:
        print("x_compatible: yes")
        print("x_force: transcoding anyway")
    else:
        print("x_compatible: no")
        for reason in compatibility.reasons:
            print(f"- {reason}")

    output_dir = args.x_output_dir or None
    output_path = x_transcoder.output_path_for(path, None, output_dir, "_x")
    if output_path.exists() and not args.x_overwrite:
        output_path = unique_output_path(output_path)

    converted = x_transcoder.transcode(options, path, output_path, info)
    output_info = x_transcoder.probe_media(converted)
    output_compatibility = x_transcoder.check_with_options(output_info, options)
    print(f"x_output: {converted}")
    if not output_compatibility.ok:
        print("x_output_compatible: no", file=sys.stderr)
        for reason in output_compatibility.reasons:
            print(f"- {reason}", file=sys.stderr)
    else:
        print("x_output_compatible: yes")
    return converted


def read_share_text(args: argparse.Namespace) -> str:
    if args.input_file:
        return Path(args.input_file).expanduser().read_text(encoding="utf-8")
    if args.share:
        return args.share
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise DouyinDownloadError("Pass share text as an argument, --input-file, or stdin.")


def media_type_message(platform: str, candidates: list[Candidate], image_candidates: list[ImageCandidate]) -> str:
    if candidates:
        return f"detected_media: video (platform={platform}, candidates={len(candidates)})"
    if image_candidates:
        return f"detected_media: images (platform={platform}, count={len(image_candidates)})"
    return f"detected_media: unknown (platform={platform})"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download accessible Douyin, Kuaishou, or Xiaohongshu media from copied share text.",
    )
    parser.add_argument(
        "share",
        nargs="?",
        help="Copied share text or URL.",
    )
    parser.add_argument(
        "--interactive",
        "-I",
        action="store_true",
        help="Start an input loop. Paste share text, press Enter to download, then continue.",
    )
    parser.add_argument(
        "-i",
        "--input-file",
        help="Read share text from a UTF-8 file.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="Directory for downloaded videos. Default: downloads",
    )
    parser.add_argument(
        "--output-name",
        help="Output filename. Default: current local time, e.g. 20260624_153012.mp4",
    )
    parser.add_argument(
        "--cookie",
        help="Optional raw Cookie header or path to a file containing one.",
    )
    parser.add_argument(
        "--platform",
        choices=PLATFORMS,
        default="auto",
        help="Platform to parse. Default: auto",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Network timeout in seconds. Default: 20",
    )
    browser_group = parser.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--browser-fallback",
        dest="browser_fallback",
        action="store_true",
        default=True,
        help="Use local Chrome/Chromium network-log fallback when direct extraction finds no video. Default: enabled",
    )
    browser_group.add_argument(
        "--no-browser-fallback",
        dest="browser_fallback",
        action="store_false",
        help="Disable the local Chrome/Chromium fallback.",
    )
    parser.add_argument(
        "--browser-timeout",
        type=float,
        default=12.0,
        help="Seconds to let browser fallback load the page. Default: 12",
    )
    parser.add_argument(
        "--chrome-path",
        help="Path or executable name for the Chromium-compatible browser used by fallback.",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the best extracted media URL without downloading.",
    )
    parser.add_argument(
        "--save-meta",
        action="store_true",
        help="Save extraction metadata next to the output file.",
    )
    parser.add_argument(
        "--show-info",
        action="store_true",
        help="Print resolution, duration, codec, bitrate, and file size after download.",
    )
    parser.add_argument(
        "--x-compatible",
        action="store_true",
        default=False,
        help="After download, check and auto-transcode unsupported formats to X-compatible H.264/AAC MP4.",
    )
    parser.add_argument(
        "--no-x-compatible",
        dest="x_compatible",
        action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--x-force",
        action="store_true",
        help="With --x-compatible, transcode even if the downloaded file already looks compatible.",
    )
    parser.add_argument(
        "--x-output-dir",
        help="Directory for X-compatible converted files. Default: same directory as downloaded file.",
    )
    parser.add_argument(
        "--x-overwrite",
        action="store_true",
        help="Overwrite existing X-compatible output file.",
    )
    parser.add_argument(
        "--x-crf",
        type=int,
        default=23,
        help="x264 CRF for --x-compatible conversion. Lower is larger/better. Default: 23",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print resolver logs and candidate URLs.",
    )
    return parser.parse_args(argv)


def handle_share_text(args: argparse.Namespace, share_text: str, cookie: str | None) -> int:
    if not share_text.strip():
        raise DouyinDownloadError("No share text was provided.")

    platform, item_id, candidates, image_candidates, logs = gather_candidates_for_request(
        share_text,
        platform=args.platform,
        cookie=cookie,
        timeout=args.timeout,
        browser_fallback=args.browser_fallback,
        browser_timeout=args.browser_timeout,
        chrome_path=args.chrome_path,
    )

    if args.verbose:
        print(f"Platform: {platform}", file=sys.stderr)
        for line in logs:
            print(line, file=sys.stderr)
        for index, candidate in enumerate(candidates, start=1):
            print(
                f"Candidate {index}: priority={candidate.priority} source={candidate.source} {candidate.url}",
                file=sys.stderr,
            )
        for index, candidate in enumerate(image_candidates, start=1):
            print(
                f"Image candidate {index}: priority={candidate.priority} source={candidate.source} {candidate.url}",
                file=sys.stderr,
            )

    if not candidates and not image_candidates:
        message = (
            "No downloadable video URL was found. The post may be private, unavailable, "
            "or the platform may require a browser cookie for this page."
        )
        if args.browser_fallback and browser_fallback_was_unavailable(logs):
            message += (
                " Direct extraction still ran, but the optional browser fallback was unavailable "
                "because no Chromium-compatible browser was found. Install Chrome, Chromium, "
                "Edge, Brave, or pass --chrome-path; use --no-browser-fallback to skip this check."
        )
        raise DouyinDownloadError(message)

    print(media_type_message(platform, candidates, image_candidates), file=sys.stderr)

    if args.print_url:
        if candidates:
            print(candidates[0].url)
        else:
            for candidate in image_candidates:
                print(candidate.url)
        return 0

    if image_candidates and not candidates:
        output_dir = Path(args.output_dir).expanduser()
        image_output_name = args.output_name or timestamp_output_stem()
        saved_paths = download_image_candidates(
            image_candidates,
            output_dir,
            output_name=image_output_name,
            overwrite=args.overwrite,
            cookie=cookie,
            timeout=args.timeout,
            referer=platform_referer(platform),
        )
        if args.save_meta:
            meta_name = f"{Path(image_output_name).stem}.json"
            save_metadata(output_dir / meta_name, platform, item_id, [], image_candidates, logs)
        for path in saved_paths:
            if args.show_info:
                print(f"file: {path}")
                print(f"size: {path.stat().st_size / 1024 / 1024:.2f} MiB ({path.stat().st_size} bytes)")
            else:
                print(path)
        return 0

    best = candidates[0]

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    default_name = timestamp_output_name()
    output_name = args.output_name or default_name
    output_path = output_dir / output_name
    if output_path.suffix.lower() != ".mp4":
        output_path = output_path.with_suffix(".mp4")
    if output_path.exists() and not args.overwrite:
        output_path = unique_output_path(output_path)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            saved_path = download_candidate(
                candidate,
                output_path,
                cookie=cookie,
                timeout=args.timeout,
                referer=platform_referer(platform),
            )
            if args.save_meta:
                save_metadata(saved_path.with_suffix(".json"), platform, item_id, candidates, image_candidates, logs)
            if args.show_info:
                print_media_info(saved_path)
            else:
                print(saved_path)
            if args.x_compatible:
                try:
                    make_x_compatible_if_needed(saved_path, args)
                except Exception as exc:
                    raise DouyinDownloadError(f"X-compatible transcode failed: {exc}") from exc
            return 0
        except DouyinDownloadError as exc:
            last_error = exc
            if args.verbose:
                print(f"Rejected candidate: {exc}", file=sys.stderr)

    raise DouyinDownloadError(f"All candidates failed. Last error: {last_error}")


def interactive_loop(args: argparse.Namespace, cookie: str | None) -> int:
    print("Media Downloader interactive mode")
    print("Paste Douyin/Kuaishou/Xiaohongshu share text or URL, then press Enter. Type exit/quit/q to leave.")
    while True:
        try:
            share_text = input("media> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not share_text:
            continue
        if share_text.lower() in {"exit", "quit", "q"}:
            return 0

        try:
            handle_share_text(args, share_text, cookie)
        except (DouyinDownloadError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
        print()


def should_start_interactive(args: argparse.Namespace) -> bool:
    return args.interactive or (not args.share and not args.input_file and sys.stdin.isatty())


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    cookie = normalize_cookie(args.cookie)
    if should_start_interactive(args):
        return interactive_loop(args, cookie)

    try:
        share_text = read_share_text(args)
        return handle_share_text(args, share_text, cookie)
    except (DouyinDownloadError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
