"""yt-dlp configuration and download management.

This module has no Qt dependency: it exposes a plain-Python ``VideoDownloader``
that reports progress through callbacks, so it can be driven from any thread.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import DownloadError, sanitize_filename

log = logging.getLogger(__name__)

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Best quality, preferring streams that live natively in an MP4 container
# (H.264/AV1 video + AAC audio) so the merge is a lossless copy.
FORMAT_WITH_FFMPEG = "bv*[ext=mp4]+ba[ext=m4a]/bv*[ext=mp4]+ba/b[ext=mp4]/bv*+ba/b"
# Without FFmpeg nothing can be merged, so only single-file formats work.
FORMAT_WITHOUT_FFMPEG = "b[ext=mp4]/b"
FORMAT_SORT = ["res", "fps", "hdr:sdr", "vcodec:h264", "acodec:aac"]

# yt-dlp needs a JavaScript runtime to unlock all YouTube formats; use
# whichever one is installed.
JS_RUNTIMES = {"deno": {}, "node": {}, "bun": {}, "quickjs": {}}

_EXISTING_EXTS = (".mp4", ".mkv", ".webm", ".m4a", ".mov")
_MAX_NAME_BYTES = 180


class InvalidUrlError(ValueError):
    """The text entered is not a supported single-video URL."""


class DownloadFailed(Exception):
    """A download could not be completed. The message is user-facing."""


class DownloadCancelledByUser(Exception):
    """The user cancelled the download."""


@dataclass(frozen=True)
class VideoInfo:
    title: str
    uploader: str
    duration: Optional[int]
    thumbnail_url: Optional[str]
    quality_label: str


@dataclass(frozen=True)
class DownloadProgress:
    fraction: Optional[float]  # 0..1, or None when unknown
    downloaded: int
    total: Optional[int]
    speed: Optional[float]  # bytes per second
    eta: Optional[float]  # seconds
    part: int  # 1-based index of the stream being downloaded
    part_count: int


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_youtube_url(text: str) -> Optional[str]:
    """Return a canonical watch URL if *text* is a YouTube video link, else None."""
    text = (text or "").strip()
    if not text or len(text) > 2048 or any(c.isspace() for c in text):
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if host.endswith("youtu.be"):
        video_id = parts[0] if parts else ""
    elif parts[:1] == ["watch"]:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
        video_id = parts[1]
    else:
        return None

    if not _VIDEO_ID.match(video_id):
        return None
    # Rebuilding the URL drops playlist/timestamp parameters, so only the
    # single video is ever downloaded.
    return f"https://www.youtube.com/watch?v={video_id}"


def validate_url(text: str) -> str:
    """Return a canonical URL or raise InvalidUrlError with a readable message."""
    text = (text or "").strip()
    if not text:
        raise InvalidUrlError("Paste a YouTube link to get started.")
    url = extract_youtube_url(text)
    if url:
        return url
    lowered = text.lower()
    if "youtu" in lowered and "list=" in lowered:
        raise InvalidUrlError("Playlists aren't supported. Paste a link to a single video.")
    raise InvalidUrlError("That doesn't look like a YouTube video link.")


def fetch_thumbnail(url: Optional[str], timeout: float = 6.0, limit: int = 2_000_000) -> Optional[bytes]:
    """Download a thumbnail image; failures are not fatal and return None."""
    if not url or not url.startswith("https://"):
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(limit)
    except Exception as exc:  # noqa: BLE001 - a missing thumbnail is cosmetic
        log.info("Thumbnail unavailable: %s", exc)
        return None


def friendly_error(message: str) -> str:
    """Translate a yt-dlp/OS error message into something a user understands."""
    msg = _ANSI.sub("", str(message)).strip()
    msg = re.sub(r"^(ERROR:\s*)?(\[[^\]]+\]\s*)?([A-Za-z0-9_-]{11}:\s*)?", "", msg)
    low = msg.lower()
    rules = [
        (("private video",), "This video is private."),
        (("confirm your age", "age-restricted", "inappropriate for some users"),
         "This video is age-restricted and can't be downloaded without signing in."),
        (("members-only", "join this channel"), "This video is only available to channel members."),
        (("not available in your country", "geo restrict", "blocked it in your country"),
         "This video isn't available in your region."),
        (("not a bot",), "YouTube is asking for verification. Please wait a while and try again."),
        (("premieres in", "live event will begin", "is_upcoming"), "This video hasn't started yet."),
        (("http error 429", "too many requests"), "YouTube is limiting requests. Please try again later."),
        (("video unavailable", "this video is unavailable", "has been removed", "does not exist",
          "has been terminated", "no longer available"),
         "This video is unavailable. It may have been removed or made private."),
        (("timed out", "unable to connect", "getaddrinfo", "name or service not known",
          "temporary failure in name resolution", "network is unreachable", "failed to resolve",
          "urlopen error", "remote end closed", "connection reset", "connection refused",
          "connection aborted", "certificate verify failed", "unable to download webpage"),
         "Network error. Check your internet connection and try again."),
        (("no space left",), "There isn't enough free disk space in the destination folder."),
        (("permission denied", "read-only file system"),
         "Snapshotter can't write to the destination folder. Choose another folder."),
        (("requested format is not available", "no video formats found"),
         "No downloadable video format was found for this video."),
        (("ffmpeg", "ffprobe", "postprocessing"),
         "FFmpeg failed while processing the video. Make sure FFmpeg is installed correctly."),
    ]
    for needles, text in rules:
        if any(n in low for n in needles):
            return text
    if len(msg) > 220:
        msg = msg[:217] + "…"
    return f"Download failed: {msg}" if msg else "Download failed for an unknown reason."


class _QuietLogger:
    """Keeps yt-dlp from writing to the terminal; routes messages to logging."""

    def debug(self, msg: str) -> None:
        if not msg.startswith("[debug] "):
            log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.info(_ANSI.sub("", msg))

    def error(self, msg: str) -> None:
        log.warning(_ANSI.sub("", msg))


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def unique_stem(directory: Path, title: str, fallback: str = "video") -> str:
    """Safe filename stem for *title* that does not clash with existing files."""
    base = sanitize_filename(title or "", restricted=False).strip().lstrip(".-").strip()
    base = _truncate_utf8(base or fallback, _MAX_NAME_BYTES)
    candidate, counter = base, 1
    while any((directory / f"{candidate}{ext}").exists() for ext in _EXISTING_EXTS):
        counter += 1
        candidate = f"{base} ({counter})"
    return candidate


def _quality_label(info: dict) -> str:
    formats = info.get("requested_formats") or [info]
    heights = [f.get("height") for f in formats if f.get("height")]
    fps_values = [f.get("fps") for f in formats if f.get("fps")]
    if not heights:
        return "Best available"
    label = f"{max(heights)}p"
    if fps_values and max(fps_values) > 30:
        label += f"{round(max(fps_values))}"
    return f"Best available · {label}"


class VideoDownloader:
    """Fetches metadata for one URL and downloads it to *destination*.

    Methods block, so call them from a worker thread. ``cancel()`` is
    thread-safe and takes effect at the next progress callback.
    """

    def __init__(
        self,
        url: str,
        destination: Path,
        on_progress: Callable[[DownloadProgress], None],
        on_status: Callable[[str], None],
    ) -> None:
        self.url = url
        self.destination = Path(destination).expanduser()
        self._on_progress = on_progress
        self._on_status = on_status
        self._cancel = threading.Event()
        self._has_ffmpeg = ffmpeg_available()
        self._info: Optional[dict] = None
        self._stream_ids: list[str] = []
        self._stream_sizes: list[Optional[int]] = []
        self._stream_done: dict[int, int] = {}
        self._last_emit = 0.0

    # -- public API -----------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def fetch_info(self) -> VideoInfo:
        opts = self._base_options()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
        except DownloadError as exc:
            raise DownloadFailed(friendly_error(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001 - network/extractor errors vary widely
            log.exception("Metadata extraction failed")
            raise DownloadFailed(friendly_error(str(exc))) from exc
        self._raise_if_cancelled()

        if not info or info.get("_type") in ("playlist", "multi_video"):
            raise DownloadFailed("Playlists aren't supported. Paste a link to a single video.")
        live_status = info.get("live_status")
        if info.get("is_live") or live_status == "is_live":
            raise DownloadFailed("Live streams can't be downloaded while they are live.")
        if live_status == "is_upcoming":
            raise DownloadFailed("This video hasn't started yet.")

        self._info = info
        requested = info.get("requested_formats") or [info]
        self._stream_ids = [str(f.get("format_id")) for f in requested]
        self._stream_sizes = [f.get("filesize") or f.get("filesize_approx") for f in requested]

        return VideoInfo(
            title=info.get("title") or "Untitled video",
            uploader=info.get("uploader") or info.get("channel") or "",
            duration=info.get("duration"),
            thumbnail_url=self._pick_thumbnail(info),
            quality_label=_quality_label(info),
        )

    def download(self) -> Path:
        """Download the video and return the path of the finished file."""
        if self._info is None:
            self.fetch_info()
        info = self._info
        assert info is not None

        try:
            self.destination.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix=".snapshotter-", dir=self.destination))
        except OSError as exc:
            raise DownloadFailed(friendly_error(str(exc))) from exc

        stem = unique_stem(self.destination, info.get("title") or "", info.get("id") or "video")
        opts = self._base_options()
        opts.update(
            {
                # Partial files live in a private temp folder inside the
                # destination and are only moved out once complete.
                "paths": {"home": str(self.destination), "temp": str(temp_dir)},
                "outtmpl": {"default": stem.replace("%", "%%") + ".%(ext)s"},
                "overwrites": False,
                "continuedl": False,
                "progress_hooks": [self._progress_hook],
                "postprocessor_hooks": [self._postprocessor_hook],
            }
        )
        if self._has_ffmpeg:
            opts["merge_output_format"] = "mp4"
            opts["postprocessors"] = [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]

        final_path: Optional[Path] = None
        try:
            self._raise_if_cancelled()
            with yt_dlp.YoutubeDL(opts) as ydl:
                # Reuse the metadata we already fetched instead of extracting twice.
                result = ydl.process_ie_result(ydl.sanitize_info(info, remove_private_keys=True), download=True)
            final_path = self._result_path(result, stem)
            self._raise_if_cancelled()
            if final_path is None or not final_path.is_file():
                raise DownloadFailed("The download finished but the output file could not be found.")
            return final_path
        except DownloadCancelledByUser:
            if final_path is not None:
                final_path.unlink(missing_ok=True)
            raise
        except DownloadFailed:
            raise
        except DownloadError as exc:
            if self.is_cancelled:
                raise DownloadCancelledByUser() from exc
            raise DownloadFailed(friendly_error(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001 - surface anything else as a readable error
            if self.is_cancelled:
                raise DownloadCancelledByUser() from exc
            log.exception("Download failed")
            raise DownloadFailed(friendly_error(str(exc))) from exc
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # -- internals -------------------------------------------------------

    def _base_options(self) -> dict:
        return {
            "format": FORMAT_WITH_FFMPEG if self._has_ffmpeg else FORMAT_WITHOUT_FFMPEG,
            "format_sort": FORMAT_SORT,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _QuietLogger(),
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 5,
            "js_runtimes": JS_RUNTIMES,
        }

    def _raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise DownloadCancelledByUser()

    @staticmethod
    def _pick_thumbnail(info: dict) -> Optional[str]:
        # Prefer a 16:9 JPEG around 480px wide: small, sharp, no letterboxing,
        # and decodable by Qt without extra image plugins.
        best, best_score = None, None
        for thumb in info.get("thumbnails") or []:
            url, width, height = thumb.get("url") or "", thumb.get("width"), thumb.get("height")
            if not url.startswith("https://") or ".webp" in url or not width or not height:
                continue
            if abs(width / height - 16 / 9) > 0.05:
                continue
            score = abs(width - 480)
            if best_score is None or score < best_score:
                best, best_score = url, score
        return best or info.get("thumbnail")

    def _result_path(self, result: Optional[dict], stem: str) -> Optional[Path]:
        for item in (result or {}).get("requested_downloads") or []:
            path = item.get("filepath") or item.get("filename")
            if path and Path(path).is_file():
                return Path(path)
        for ext in (".mp4", ".mkv", ".webm"):
            candidate = self.destination / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
        return None

    def _stream_index(self, data: dict) -> int:
        format_id = str((data.get("info_dict") or {}).get("format_id"))
        try:
            return self._stream_ids.index(format_id)
        except ValueError:
            return 0

    def _progress_hook(self, data: dict) -> None:
        self._raise_if_cancelled()
        status = data.get("status")
        if status not in ("downloading", "finished"):
            return

        index = self._stream_index(data)
        count = max(1, len(self._stream_ids))
        downloaded = int(data.get("downloaded_bytes") or 0)
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        if total:
            self._stream_sizes[index] = int(total)

        if status == "finished":
            self._stream_done[index] = downloaded or int(total or 0)
        else:
            now = time.monotonic()
            if now - self._last_emit < 0.12:
                return
            self._last_emit = now

        done_before = sum(v for i, v in self._stream_done.items() if i != index)
        current = self._stream_done.get(index, downloaded)
        all_downloaded = done_before + current

        if all(self._stream_sizes):
            grand_total = int(sum(self._stream_sizes))  # type: ignore[arg-type]
            fraction = min(all_downloaded / grand_total, 1.0) if grand_total else None
        else:
            grand_total = None
            others_done = sum(1 for i in self._stream_done if i != index)
            if index in self._stream_done:
                stream_fraction = 1.0
            else:
                stream_fraction = (downloaded / total) if total else 0.0
            fraction = min((others_done + stream_fraction) / count, 1.0)

        speed = data.get("speed")
        eta = data.get("eta")
        if grand_total and speed:
            eta = max(grand_total - all_downloaded, 0) / speed

        self._on_progress(
            DownloadProgress(
                fraction=fraction,
                downloaded=all_downloaded,
                total=grand_total,
                speed=speed,
                eta=eta,
                part=index + 1,
                part_count=count,
            )
        )

    def _postprocessor_hook(self, data: dict) -> None:
        if data.get("status") != "started":
            return
        self._raise_if_cancelled()
        name = data.get("postprocessor")
        # yt-dlp reports post-processors by key, without "FFmpeg"/"PP" affixes.
        if name == "Merger":
            self._on_status("Merging video and audio…")
        elif name == "VideoRemuxer":
            self._on_status("Preparing MP4…")
        elif name == "MoveFiles":
            self._on_status("Finishing up…")
