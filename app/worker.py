"""Background download worker and thread communication."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from .downloader import (
    DownloadCancelledByUser,
    DownloadFailed,
    VideoDownloader,
    fetch_thumbnail,
)

log = logging.getLogger(__name__)


class DownloadWorker(QObject):
    """Runs one download inside a QThread and reports back through signals.

    Signals are emitted from the worker thread; Qt delivers them to slots in
    the GUI thread through queued connections.
    """

    info_ready = Signal(object)  # VideoInfo
    thumbnail_ready = Signal(bytes)
    progress = Signal(object)  # DownloadProgress
    status = Signal(str)
    succeeded = Signal(str)  # path of the finished file
    failed = Signal(str)  # user-facing error message
    cancelled = Signal()
    finished = Signal()  # always emitted last

    def __init__(self, url: str, destination: Path) -> None:
        super().__init__()
        self._downloader = VideoDownloader(
            url,
            destination,
            on_progress=self.progress.emit,
            on_status=self.status.emit,
        )

    def cancel(self) -> None:
        """Request cancellation. Safe to call from the GUI thread."""
        self._downloader.cancel()

    @Slot()
    def run(self) -> None:
        try:
            info = self._downloader.fetch_info()
            self.info_ready.emit(info)
            thumbnail = fetch_thumbnail(info.thumbnail_url)
            if thumbnail:
                self.thumbnail_ready.emit(thumbnail)
            path = self._downloader.download()
            self.succeeded.emit(str(path))
        except DownloadCancelledByUser:
            self.cancelled.emit()
        except DownloadFailed as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - never let the thread die silently
            log.exception("Unexpected download error")
            self.failed.emit(f"Unexpected error: {exc}")
        finally:
            self.finished.emit()
