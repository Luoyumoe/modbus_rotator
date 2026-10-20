from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class CompassWidget(QWidget):
    azimuthClicked = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_azimuth = 0.0
        self.target_azimuth: float | None = None
        self.beam_width = 0.0
        self.setMinimumSize(360, 360)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_angles(self, current: float, target: float | None = None) -> None:
        self.current_azimuth = float(current) % 360.0
        self.target_azimuth = None if target is None else float(target) % 360.0
        self.update()

    def set_beam_width(self, degrees: float) -> None:
        self.beam_width = max(0.0, float(degrees))
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        center = self.rect().center()
        dx = event.position().x() - center.x()
        dy = center.y() - event.position().y()
        if math.hypot(dx, dy) < 20:
            return
        angle = math.degrees(math.atan2(dx, dy)) % 360.0
        self.azimuthClicked.emit(angle)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#10151b"))
        side = min(self.width(), self.height()) - 28
        radius = side / 2.0
        center = QPointF(self.rect().center())
        painter.setPen(QPen(QColor("#394652"), 2))
        painter.drawEllipse(center, radius, radius)
        # Beam sector.
        if self.beam_width > 0:
            painter.setBrush(QColor(64, 147, 214, 45))
            painter.setPen(Qt.PenStyle.NoPen)
            rect = center.x() - radius, center.y() - radius, side, side
            start = int((90.0 - self.current_azimuth - self.beam_width / 2.0) * 16)
            span = int(self.beam_width * 16)
            painter.drawPie(*rect, start, span)
        # Degree ticks and cardinal labels.
        for degree in range(0, 360, 5):
            length = 13 if degree % 30 == 0 else 7
            radians = math.radians(degree)
            outer = QPointF(center.x() + math.sin(radians) * radius, center.y() - math.cos(radians) * radius)
            inner = QPointF(
                center.x() + math.sin(radians) * (radius - length),
                center.y() - math.cos(radians) * (radius - length),
            )
            painter.setPen(QPen(QColor("#72818d"), 2 if degree % 30 == 0 else 1))
            painter.drawLine(inner, outer)
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        for text, degree in (
            ("N", 0), ("NE", 45), ("E", 90), ("SE", 135),
            ("S", 180), ("SW", 225), ("W", 270), ("NW", 315),
        ):
            radians = math.radians(degree)
            label_radius = radius - (30 if len(text) == 1 else 34)
            point = QPointF(center.x() + math.sin(radians) * label_radius, center.y() - math.cos(radians) * label_radius)
            painter.setPen(QColor("#e6edf3"))
            painter.drawText(point.x() - (10 if len(text) == 1 else 12), point.y() + 5, text)

        self._draw_pointer(painter, center, radius - 34, self.current_azimuth, QColor("#48d597"), 4, False)
        if self.target_azimuth is not None:
            self._draw_pointer(painter, center, radius - 38, self.target_azimuth, QColor("#f5b84b"), 2, True)
        painter.setBrush(QColor("#48d597"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 5, 5)

    @staticmethod
    def _draw_pointer(painter: QPainter, center: QPointF, length: float, angle: float, color: QColor, width: int, dashed: bool) -> None:
        radians = math.radians(angle)
        end = QPointF(center.x() + math.sin(radians) * length, center.y() - math.cos(radians) * length)
        pen = QPen(color, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(center, end)


__all__ = ["CompassWidget"]

