"""Обёртка над yt-dlp. Синхронная (вызывается из воркера через asyncio.to_thread)."""

import shutil
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from app.services.links import MediaLink, Platform

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXT = {".mp3", ".m4a", ".opus", ".ogg"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_ITEMS = 10


class Fmt(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class ErrorCode(StrEnum):
    TOO_BIG = "too_big"
    TOO_LONG = "too_long"
    PRIVATE = "private"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class DownloadError(Exception):
    def __init__(self, code: ErrorCode, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(slots=True)
class MediaFile:
    path: Path
    kind: str  # video | audio | photo
    width: int | None = None
    height: int | None = None
    duration: int | None = None


@dataclass(slots=True)
class DownloadResult:
    title: str
    workdir: Path
    files: list[MediaFile] = field(default_factory=list)
    uploader: str | None = None

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def _size(f: dict[str, Any], duration: float | None) -> int | None:
    size = f.get("filesize") or f.get("filesize_approx")
    if size:
        return int(size)
    tbr = f.get("tbr")
    if tbr and duration:
        return int(float(tbr) * 1000 / 8 * duration)
    return None


def select_youtube_format(
    formats: list[dict[str, Any]], limit: int, duration: float | None, max_height: int = 720
) -> str | None:
    """Лучшее H.264 ≤ max_height, влезающее в лимит Telegram (играет на всех клиентах); иначе AV1 и т.п."""
    budget = int(limit * 0.97)
    audios = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    audios.sort(key=lambda f: (f.get("ext") == "m4a", f.get("abr") or 0), reverse=True)
    audio = next((a for a in audios if a.get("ext") == "m4a"), audios[0] if audios else None)
    audio_size = (_size(audio, duration) or 0) if audio else 0

    videos = [
        f
        for f in formats
        if f.get("acodec") == "none"
        and f.get("vcodec") not in (None, "none")
        and f.get("ext") == "mp4"
        and (f.get("height") or 0) <= max_height
        and f.get("protocol", "https") in ("https", "http")
    ]
    videos.sort(
        key=lambda f: (
            str(f.get("vcodec", "")).startswith("avc1"),
            f.get("height") or 0,
            f.get("tbr") or 0,
        ),
        reverse=True,
    )
    if audio:
        for v in videos:
            vs = _size(v, duration)
            if vs is not None and vs + audio_size <= budget:
                return f"{v['format_id']}+{audio['format_id']}"

    progressive = [
        f
        for f in formats
        if f.get("acodec") not in (None, "none")
        and f.get("vcodec") not in (None, "none")
        and f.get("ext") == "mp4"
        and (f.get("height") or 0) <= max_height
    ]
    progressive.sort(key=lambda f: f.get("height") or 0, reverse=True)
    for p in progressive:
        size = _size(p, duration)
        if size is None or size <= budget:
            return str(p["format_id"])
    return None


def select_audio_format(formats: list[dict[str, Any]], limit: int, duration: float | None) -> str | None:
    audios = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    audios.sort(key=lambda f: f.get("abr") or 0, reverse=True)
    for a in audios:
        size = _size(a, duration)
        # mp3 192k после конвертации может быть больше исходника — оцениваем по битрейту
        mp3_size = int(192_000 / 8 * duration) if duration else 0
        if (size is None or size <= limit) and mp3_size <= limit:
            return str(a["format_id"])
    return None


def _classify_error(exc: Exception) -> DownloadError:
    msg = str(exc).lower()
    if "private" in msg or "login" in msg or "cookies" in msg or "sign in" in msg:
        return DownloadError(ErrorCode.PRIVATE, str(exc)[:500])
    if "file is larger than max-filesize" in msg:
        return DownloadError(ErrorCode.TOO_BIG, str(exc)[:500])
    if "unavailable" in msg or "not available" in msg or "removed" in msg or "404" in msg:
        return DownloadError(ErrorCode.UNAVAILABLE, str(exc)[:500])
    return DownloadError(ErrorCode.FAILED, str(exc)[:500])


class Downloader:
    def __init__(
        self,
        *,
        base_dir: str,
        limit_bytes: int,
        proxy: str = "",
        cookies_file: str = "",
        timeout: int = 600,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.limit = limit_bytes
        self.proxy = proxy
        self.cookies_file = cookies_file
        self.timeout = timeout

    def _opts(self, workdir: Path, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "outtmpl": str(workdir / "%(id)s_%(autonumber)s.%(ext)s"),
            "restrictfilenames": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "max_filesize": self.limit,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "playlist_items": f"1-{MAX_ITEMS}",
        }
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.cookies_file and Path(self.cookies_file).exists():
            opts["cookiefile"] = self.cookies_file
        opts.update(extra)
        return opts

    def download(self, link: MediaLink, fmt: Fmt, *, max_duration_sec: int = 0) -> DownloadResult:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="dl_", dir=self.base_dir))
        try:
            return self._download(link, fmt, workdir, max_duration_sec)
        except DownloadError:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        except YtDlpDownloadError as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise _classify_error(exc) from exc
        except Exception as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise DownloadError(ErrorCode.FAILED, repr(exc)[:500]) from exc

    def _download(self, link: MediaLink, fmt: Fmt, workdir: Path, max_duration_sec: int) -> DownloadResult:
        extra: dict[str, Any] = {}
        if link.platform == Platform.INSTAGRAM:
            extra["noplaylist"] = False

        with yt_dlp.YoutubeDL(self._opts(workdir, **extra)) as probe:
            info = probe.extract_info(link.url, download=False, process=False)
        if not isinstance(info, dict):
            raise DownloadError(ErrorCode.UNAVAILABLE, "empty info")

        duration = info.get("duration")
        if max_duration_sec and duration and duration > max_duration_sec:
            raise DownloadError(ErrorCode.TOO_LONG, f"{duration}s")

        if fmt == Fmt.AUDIO:
            extra["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
                {"key": "FFmpegMetadata"},
            ]

        if link.platform == Platform.YOUTUBE:
            with yt_dlp.YoutubeDL(self._opts(workdir)) as ydl:
                full = ydl.extract_info(link.url, download=False)
            formats = (full or {}).get("formats") or []
            chosen = (
                select_audio_format(formats, self.limit, duration)
                if fmt == Fmt.AUDIO
                else select_youtube_format(formats, self.limit, duration)
            )
            if not chosen:
                raise DownloadError(ErrorCode.TOO_BIG, "no format fits the limit")
            extra["format"] = chosen
        elif fmt == Fmt.AUDIO:
            extra["format"] = "bestaudio/best"
        else:
            lim = self.limit
            extra["format"] = f"best[ext=mp4][filesize<?{lim}]/bv*[ext=mp4]+ba/best[filesize<?{lim}]/best"

        with yt_dlp.YoutubeDL(self._opts(workdir, **extra)) as ydl:
            result = ydl.extract_info(link.url, download=True)
        result = result or {}

        entries: list[dict[str, Any]] = [e for e in (result.get("entries") or [result]) if e]
        meta = entries[0] if entries else {}
        files = self._collect(workdir, meta)
        if not files:
            raise DownloadError(ErrorCode.UNAVAILABLE, "no files downloaded")
        too_big = [f for f in files if f.path.stat().st_size > self.limit]
        if too_big:
            raise DownloadError(ErrorCode.TOO_BIG, "file exceeds limit")
        title = str(result.get("title") or meta.get("title") or "")
        if link.platform == Platform.INSTAGRAM and title.lower().startswith("video by"):
            title = ""
        return DownloadResult(
            title=title[:200],
            workdir=workdir,
            files=files,
            uploader=result.get("uploader") or meta.get("uploader"),
        )

    def _collect(self, workdir: Path, meta: dict[str, Any]) -> list[MediaFile]:
        files: list[MediaFile] = []
        for path in sorted(workdir.iterdir()):
            ext = path.suffix.lower()
            if path.name.endswith((".part", ".ytdl")):
                continue
            if ext in VIDEO_EXT:
                files.append(
                    MediaFile(
                        path,
                        "video",
                        width=meta.get("width"),
                        height=meta.get("height"),
                        duration=int(meta["duration"]) if meta.get("duration") else None,
                    )
                )
            elif ext in AUDIO_EXT:
                dur = int(meta["duration"]) if meta.get("duration") else None
                files.append(MediaFile(path, "audio", duration=dur))
            elif ext in PHOTO_EXT:
                files.append(MediaFile(path, "photo"))
        return files[:MAX_ITEMS]
