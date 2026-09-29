import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qs, urlparse


class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


@dataclass(frozen=True, slots=True)
class MediaLink:
    platform: Platform
    url: str
    media_id: str | None

    def cache_key(self, fmt: str) -> str:
        ident = self.media_id or self.url
        return f"{self.platform}:{ident}:{fmt}"[:255]


URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_YT_HOSTS = {"youtube.com", "m.youtube.com", "www.youtube.com", "music.youtube.com", "youtu.be"}
_IG_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
_TT_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"}

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_PATH = re.compile(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})")
_IG_PATH = re.compile(r"^/(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
_TT_PATH = re.compile(r"/video/(\d+)")


def _youtube_id(host: str, path: str, query: str) -> str | None:
    if host == "youtu.be":
        candidate = path.strip("/").split("/")[0]
        return candidate if _YT_ID.match(candidate) else None
    if path == "/watch":
        v = parse_qs(query).get("v", [""])[0]
        return v if _YT_ID.match(v) else None
    m = _YT_PATH.match(path)
    return m.group(1) if m else None


def parse_link(raw: str) -> MediaLink | None:
    raw = raw.strip().rstrip(".,!?)")
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"

    if host in _YT_HOSTS:
        vid = _youtube_id(host, path, parsed.query)
        if not vid:
            return None
        return MediaLink(Platform.YOUTUBE, f"https://www.youtube.com/watch?v={vid}", vid)

    if host in _IG_HOSTS:
        m = _IG_PATH.match(path)
        if not m:
            return None
        return MediaLink(Platform.INSTAGRAM, f"https://www.instagram.com/p/{m.group(1)}/", m.group(1))

    if host in _TT_HOSTS:
        m = _TT_PATH.search(path)
        clean = f"https://{host}{path}"
        return MediaLink(Platform.TIKTOK, clean, m.group(1) if m else None)

    return None


def find_link(text: str | None) -> MediaLink | None:
    if not text:
        return None
    for match in URL_RE.finditer(text):
        link = parse_link(match.group(0))
        if link:
            return link
    return None
