"""Transparent always-on-top subtitle window (PyQt6)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from .config import Settings

log = logging.getLogger(__name__)


class SubtitleWindow(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

        # Window flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint           # no title bar
            | Qt.WindowType.WindowStaysOnTopHint        # always on top
            | Qt.WindowType.WindowTransparentForInput   # click-through
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # transparent background
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)  # don't steal focus

        # Position window on the target screen
        screens = QApplication.screens()
        idx = settings.screen
        if idx >= len(screens):
            log.warning("screen=%d not found (%d screen(s) detected). Using screen 0.", idx, len(screens))
            idx = 0
        target = screens[idx]
        log.info("Using screen [%d]: %s", idx, target.name())
        screen = target.availableGeometry()  # area excluding the Dock
        win_w = int(screen.width() * settings.window_width_ratio)
        win_h = 90
        x = screen.x() + (screen.width() - win_w) // 2
        y = screen.y() + settings.screen_margin_y
        self.setGeometry(x, y, win_w, win_h)
        log.info("Overlay window: %dx%d at (%d, %d)", win_w, win_h, x, y)

        # Subtitle label
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setFont(QFont("Helvetica", settings.font_size, QFont.Weight.Bold))
        self.label.setGeometry(0, 0, win_w, win_h)

        color = QColor(settings.bg_color)
        self._bg_rgba = f"rgba({color.red()}, {color.green()}, {color.blue()}, {settings.bg_opacity})"
        self._set_style(settings.font_color)

        # Timer to auto-clear subtitle
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear)

        # Small status badge (gain level etc.) in the bottom-right corner of the bar
        self.status = QLabel("", self)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status.setFont(QFont("Helvetica", max(10, settings.font_size // 2)))
        self.status.setStyleSheet(f"""
            QLabel {{
                color: #ffd54f;
                background-color: {self._bg_rgba};
                border-radius: 6px;
                padding: 2px 8px;
            }}
        """)
        self.status.adjustSize()
        self.status.hide()
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self.status.hide)

    def _set_style(self, font_color: str):
        self.label.setStyleSheet(f"""
            QLabel {{
                color: {font_color};
                background-color: {self._bg_rgba};
                border-radius: 8px;
                padding: 6px 14px;
            }}
        """)

    def show_text(self, text: str):
        """Show finalized text and (re)start the auto-clear timer."""
        self._set_style(self.settings.font_color)
        self.label.setText(text)
        self._clear_timer.start(int(self.settings.subtitle_seconds * 1000))

    def show_partial(self, text: str):
        """Show in-progress text — does not start the auto-clear timer."""
        self._clear_timer.stop()
        self._set_style(self.settings.font_color_partial)
        self.label.setText(text)

    def show_status(self, text: str, seconds: float = 1.5):
        """Briefly show a small status badge (e.g. current gain) without touching the subtitle."""
        self.status.setText(text)
        self.status.adjustSize()
        self.status.move(self.width() - self.status.width() - 6, self.height() - self.status.height() - 6)
        self.status.show()
        self.status.raise_()
        self._status_timer.start(int(seconds * 1000))

    def _clear(self):
        self.label.setText("")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()
