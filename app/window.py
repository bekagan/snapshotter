"""Main window: URL entry, download progress and result screens."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QSize, QStandardPaths, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import styles
from .downloader import (
    DownloadProgress,
    InvalidUrlError,
    VideoInfo,
    extract_youtube_url,
    ffmpeg_available,
    validate_url,
)
from .worker import DownloadWorker

THUMB_WIDTH, THUMB_HEIGHT = 128, 72


def default_download_dir() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    return Path(location) if location else Path.home() / "Downloads"


def display_path(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def format_bytes(value: Optional[float]) -> str:
    if value is None:
        return "?"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_seconds(value: Optional[float]) -> str:
    seconds = int(round(value or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def shorten(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class ElidedLabel(QLabel):
    """Single-line label that elides its text to fit the available width."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__()
        self._full_text = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._update_text()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full_text = text
        self.setToolTip(text)
        self._update_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._update_text()

    def _update_text(self) -> None:
        elided = self.fontMetrics().elidedText(self._full_text, self._mode, max(self.width(), 10))
        super().setText(elided)


def rounded_pixmap(source: QPixmap, width: int, height: int, radius: float, scale: float) -> QPixmap:
    """Scale *source* to cover width x height and clip it to a rounded rectangle."""
    target = QPixmap(round(width * scale), round(height * scale))
    target.fill(Qt.GlobalColor.transparent)
    scaled = source.scaled(
        target.size(),
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, target.width(), target.height(), radius * scale, radius * scale)
    painter.setClipPath(path)
    painter.drawPixmap(
        (target.width() - scaled.width()) // 2,
        (target.height() - scaled.height()) // 2,
        scaled,
    )
    painter.end()
    target.setDevicePixelRatio(scale)
    return target


class MainWindow(QMainWindow):
    PAGE_INPUT, PAGE_PROGRESS, PAGE_DONE, PAGE_ERROR = range(4)

    def __init__(self, app_icon: QIcon) -> None:
        super().__init__()
        self.setWindowTitle("Snapshotter")
        self.setWindowIcon(app_icon)
        self.setMinimumSize(360, 340)
        self.resize(400, 340)

        self._app_icon = app_icon
        self._destination = default_download_dir()
        self._has_ffmpeg = ffmpeg_available()
        self._thread: Optional[QThread] = None
        self._worker: Optional[DownloadWorker] = None
        self._last_url: Optional[str] = None
        self._last_file: Optional[Path] = None
        self._quit_when_idle = False
        self._clipboard_checked = False

        self._build_ui()
        self._show_page(self.PAGE_INPUT)

    # -- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget(objectName="root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(14)
        layout.addLayout(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_input_page())
        self.stack.addWidget(self._build_progress_page())
        self.stack.addWidget(self._build_done_page())
        self.stack.addWidget(self._build_error_page())
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(root)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(self._app_icon.pixmap(QSize(32, 32), self.devicePixelRatioF() or 1.0))
        logo.setFixedSize(32, 32)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(QLabel("Snapshotter", objectName="appTitle"))
        titles.addWidget(QLabel("Download a video", objectName="appSubtitle"))

        header.addWidget(logo)
        header.addLayout(titles)
        header.addStretch(1)
        return header

    @staticmethod
    def _muted(text: str = "") -> QLabel:
        label = QLabel(text)
        label.setProperty("muted", True)
        return label

    def _option_row(self, name: str, value: QWidget, trailing: Optional[QWidget] = None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = self._muted(name)
        label.setFixedWidth(62)
        row.addWidget(label)
        row.addWidget(value, 1)
        if trailing is not None:
            row.addWidget(trailing)
        return row

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste a YouTube link")
        self.url_edit.addAction(styles.icon("link", 16), QLineEdit.ActionPosition.LeadingPosition)
        paste_action = self.url_edit.addAction(
            styles.icon("clipboard", 16, styles.TEXT), QLineEdit.ActionPosition.TrailingPosition
        )
        paste_action.setToolTip("Paste from clipboard")
        paste_action.triggered.connect(self._paste_from_clipboard)
        self.url_edit.returnPressed.connect(self._start_download)
        self.url_edit.textEdited.connect(lambda _text: self._set_hint(""))
        layout.addWidget(self.url_edit)

        self.hint = QLabel(objectName="hint")
        self.hint.setMinimumHeight(18)
        layout.addWidget(self.hint)

        card = QFrame(objectName="card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 8, 10)
        card_layout.setSpacing(8)

        card_layout.addLayout(self._option_row("Format", QLabel("MP4")))
        if self._has_ffmpeg:
            quality = QLabel("Best available")
        else:
            quality = QLabel("Limited (FFmpeg not found)", objectName="warning")
            quality.setToolTip("Install FFmpeg to download the best available quality.")
        card_layout.addLayout(self._option_row("Quality", quality))

        self.folder_label = ElidedLabel(display_path(self._destination))
        folder_button = QToolButton()
        folder_button.setIcon(styles.icon("folder", 16, styles.TEXT))
        folder_button.setToolTip("Choose download folder")
        folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        folder_button.clicked.connect(self._choose_folder)
        card_layout.addLayout(self._option_row("Save to", self.folder_label, folder_button))
        layout.addSpacing(4)
        layout.addWidget(card)

        layout.addStretch(1)
        self.download_button = QPushButton(" Download Video", objectName="primary")
        self.download_button.setIcon(styles.icon("download", 18, "#FFFFFF"))
        self.download_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_button.clicked.connect(self._start_download)
        layout.addWidget(self.download_button)
        return page

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = QFrame(objectName="card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(12)
        self.thumbnail = QLabel(objectName="thumbnail")
        self.thumbnail.setFixedSize(THUMB_WIDTH, THUMB_HEIGHT)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        self.video_title = QLabel(objectName="videoTitle")
        self.video_title.setWordWrap(True)
        self.video_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.video_title.setMaximumHeight(self.video_title.fontMetrics().lineSpacing() * 3)
        self.video_meta = self._muted()
        self.video_meta.setWordWrap(True)
        self.video_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text_column.addWidget(self.video_title)
        text_column.addWidget(self.video_meta)
        text_column.addStretch(1)
        card_layout.addLayout(text_column, 1)
        layout.addWidget(card)

        layout.addSpacing(2)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        stats = QHBoxLayout()
        self.stats_left = self._muted()
        self.stats_right = self._muted()
        self.stats_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        stats.addWidget(self.stats_left)
        stats.addStretch(1)
        stats.addWidget(self.stats_right)
        layout.addLayout(stats)

        layout.addStretch(1)
        self.cancel_button = QPushButton(" Cancel")
        self.cancel_button.setIcon(styles.icon("close", 16, styles.TEXT))
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self._cancel_download)
        layout.addWidget(self.cancel_button)
        return page

    def _result_page(self, badge_name: str, icon_name: str, icon_color: str, headline: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addStretch(1)

        badge = QLabel(objectName=badge_name)
        badge.setFixedSize(52, 52)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(styles.icon_pixmap(icon_name, 26, icon_color))
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(6)

        title = QLabel(headline, objectName="headline")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        return page, layout

    def _button_row(self, secondary: QPushButton, primary: QPushButton) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        for button in (secondary, primary):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(button, 1)
        return row

    def _build_done_page(self) -> QWidget:
        page, layout = self._result_page("badgeSuccess", "check", styles.SUCCESS, "Download complete")

        self.done_filename = ElidedLabel()
        self.done_filename.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.done_filename.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.done_filename)
        self.done_location = ElidedLabel()
        self.done_location.setProperty("muted", True)
        self.done_location.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.done_location)
        layout.addStretch(1)

        another = QPushButton(" Download Another")
        another.setIcon(styles.icon("download", 16, styles.TEXT))
        another.clicked.connect(self._reset_to_input)
        open_folder = QPushButton(" Open Folder", objectName="primary")
        open_folder.setIcon(styles.icon("folder", 16, "#FFFFFF"))
        open_folder.clicked.connect(self._open_folder)
        layout.addLayout(self._button_row(another, open_folder))
        return page

    def _build_error_page(self) -> QWidget:
        page, layout = self._result_page("badgeError", "alert", styles.ACCENT, "Download failed")

        self.error_message = self._muted()
        self.error_message.setWordWrap(True)
        self.error_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.error_message)
        layout.addStretch(1)

        back = QPushButton("Back")
        back.clicked.connect(self._reset_to_input)
        retry = QPushButton(" Try Again", objectName="primary")
        retry.setIcon(styles.icon("retry", 16, "#FFFFFF"))
        retry.clicked.connect(self._retry)
        layout.addLayout(self._button_row(back, retry))
        return page

    # -- helpers ----------------------------------------------------------

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == self.PAGE_INPUT:
            self.url_edit.setFocus()

    def _set_hint(self, text: str, state: str = "") -> None:
        self.hint.setText(text)
        self.hint.setProperty("state", state)
        self.hint.style().unpolish(self.hint)
        self.hint.style().polish(self.hint)

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.progress_bar.setRange(0, 0)
        elif self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1000)

    def _set_thumbnail_placeholder(self) -> None:
        self.thumbnail.setPixmap(styles.icon_pixmap("film", 26, styles.TEXT_DISABLED))

    # -- user actions -----------------------------------------------------

    def _paste_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not text:
            self._set_hint("The clipboard is empty.", "error")
            return
        self.url_edit.setText(text)
        try:
            validate_url(text)
        except InvalidUrlError as exc:
            self._set_hint(str(exc), "error")
        else:
            self._set_hint("")

    def _check_clipboard(self) -> None:
        if self._clipboard_checked:
            return
        self._clipboard_checked = True
        if self.stack.currentIndex() != self.PAGE_INPUT or self.url_edit.text().strip():
            return
        url = extract_youtube_url(QGuiApplication.clipboard().text())
        if url:
            self.url_edit.setText(url)
            self.url_edit.setCursorPosition(0)
            self._set_hint("YouTube link found in your clipboard.", "info")

    def _choose_folder(self) -> None:
        start = str(self._destination if self._destination.is_dir() else Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose Download Folder", start)
        if chosen:
            self._destination = Path(chosen)
            self.folder_label.setText(display_path(self._destination))

    def _start_download(self) -> None:
        if self._thread is not None:
            return  # one download at a time
        try:
            url = validate_url(self.url_edit.text())
        except InvalidUrlError as exc:
            self._set_hint(str(exc), "error")
            self.url_edit.setFocus()
            return

        self._last_url = url
        self._set_hint("")
        self.download_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText(" Cancel")
        self.video_title.setText("Loading video…")
        self.video_title.setToolTip("")
        self.video_meta.setText("MP4 · Best available")
        self._set_thumbnail_placeholder()
        self.status_label.setText("Fetching video info…")
        self.stats_left.setText("")
        self.stats_right.setText("")
        self._set_busy(True)
        self._show_page(self.PAGE_PROGRESS)

        thread = QThread(self)
        worker = DownloadWorker(url, self._destination)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.info_ready.connect(self._on_info)
        worker.thumbnail_ready.connect(self._on_thumbnail)
        worker.progress.connect(self._on_progress)
        worker.status.connect(self._on_status)
        worker.succeeded.connect(self._on_succeeded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._thread, self._worker = thread, worker
        thread.start()

    def _cancel_download(self) -> None:
        if self._worker is None:
            return
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling…")
        self.status_label.setText("Cancelling…")
        self._worker.cancel()

    def _retry(self) -> None:
        if self._last_url:
            self.url_edit.setText(self._last_url)
        self._show_page(self.PAGE_INPUT)
        self._start_download()

    def _reset_to_input(self) -> None:
        self.url_edit.clear()
        self._set_hint("")
        self._show_page(self.PAGE_INPUT)

    def _open_folder(self) -> None:
        folder = self._last_file.parent if self._last_file else self._destination
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.information(self, "Snapshotter", f"The video was saved to:\n{folder}")

    # -- worker signal handlers -------------------------------------------

    def _on_info(self, info: VideoInfo) -> None:
        self.video_title.setText(shorten(info.title))
        self.video_title.setToolTip(info.title)
        meta = f"MP4 · {info.quality_label}"
        if info.duration:
            meta += f" · {format_seconds(info.duration)}"
        self.video_meta.setText(meta)
        if self.cancel_button.isEnabled():
            self.status_label.setText("Starting download…")

    def _on_thumbnail(self, data: bytes) -> None:
        source = QPixmap()
        if source.loadFromData(data):
            scale = self.devicePixelRatioF() or 1.0
            self.thumbnail.setPixmap(rounded_pixmap(source, THUMB_WIDTH, THUMB_HEIGHT, 6, scale))

    def _on_progress(self, progress: DownloadProgress) -> None:
        if not self.cancel_button.isEnabled():
            return  # cancelling; keep the "Cancelling…" state
        if progress.part_count > 1:
            self.status_label.setText(f"Downloading… (stream {progress.part} of {progress.part_count})")
        else:
            self.status_label.setText("Downloading…")

        if progress.fraction is None:
            self._set_busy(True)
            left = format_bytes(progress.downloaded)
        else:
            self._set_busy(False)
            self.progress_bar.setValue(round(progress.fraction * 1000))
            percent = f"{progress.fraction * 100:.0f}%"
            if progress.total:
                left = f"{percent} · {format_bytes(progress.downloaded)} of {format_bytes(progress.total)}"
            else:
                left = f"{percent} · {format_bytes(progress.downloaded)}"
        self.stats_left.setText(left)

        right = []
        if progress.speed:
            right.append(f"{format_bytes(progress.speed)}/s")
        if progress.eta is not None:
            right.append(f"{format_seconds(progress.eta)} left")
        self.stats_right.setText(" · ".join(right))

    def _on_status(self, text: str) -> None:
        if not self.cancel_button.isEnabled():
            return
        self.status_label.setText(text)
        self.stats_right.setText("")
        self._set_busy(True)

    def _on_succeeded(self, path: str) -> None:
        self._last_file = Path(path)
        self.done_filename.setText(self._last_file.name)
        self.done_location.setText(f"Saved to {display_path(self._last_file.parent)}")
        self._show_page(self.PAGE_DONE)

    def _on_failed(self, message: str) -> None:
        self.error_message.setText(message)
        self._show_page(self.PAGE_ERROR)

    def _on_cancelled(self) -> None:
        self._show_page(self.PAGE_INPUT)
        self._set_hint("Download cancelled.")

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.download_button.setEnabled(True)
        if self._quit_when_idle:
            QGuiApplication.quit()

    # -- lifecycle ----------------------------------------------------------

    def is_busy(self) -> bool:
        return self._thread is not None

    def wait_for_worker(self, timeout_ms: int) -> bool:
        """Block until the worker thread exits. Returns False on timeout."""
        thread = self._thread
        return thread is None or thread.wait(timeout_ms)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt naming
        super().changeEvent(event)
        # Wayland only exposes the clipboard to focused windows, so look at it
        # once the window is first activated rather than at construction time.
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and not self._clipboard_checked:
            QTimer.singleShot(50, self._check_clipboard)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if not self.is_busy():
            event.accept()
            QGuiApplication.quit()
            return
        answer = QMessageBox.question(
            self,
            "Quit Snapshotter?",
            "A download is in progress. Cancel it and quit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        event.ignore()
        if answer == QMessageBox.StandardButton.Yes and self._worker is not None:
            # Let the worker clean up its temporary files, then quit once the
            # thread has finished (see _on_thread_finished).
            self._quit_when_idle = True
            self._worker.cancel()
            self.hide()
            QTimer.singleShot(15000, QGuiApplication.quit)
