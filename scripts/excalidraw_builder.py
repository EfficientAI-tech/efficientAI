"""Helper to build well-spaced Excalidraw (.excalidraw) JSON files."""

from __future__ import annotations

import json
import random
import string
from pathlib import Path
from typing import Any


def _id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _seed() -> int:
    return random.randint(1, 2_000_000_000)


def _line_count(text: str) -> int:
    return max(1, len(text.split("\n")))


def _estimate_height(text: str, width: float, font_size: int, min_h: float) -> float:
    lines = 0
    chars_per_line = max(12, int(width / (font_size * 0.55)))
    for part in text.split("\n"):
        lines += max(1, (len(part) + chars_per_line - 1) // chars_per_line)
    return max(min_h, lines * font_size * 1.45 + 28)


class ExcalidrawBuilder:
    """Build diagrams with consistent spacing and auto-sized boxes."""

    def __init__(self, *, canvas_width: float = 1400) -> None:
        self.elements: list[dict[str, Any]] = []
        self.canvas_width = canvas_width
        self._max_y = 0.0
        self._max_x = 0.0

    def _track_bounds(self, x: float, y: float, w: float, h: float) -> None:
        self._max_x = max(self._max_x, x + w)
        self._max_y = max(self._max_y, y + h)

    def box(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        *,
        bg: str = "#a5d8ff",
        stroke: str = "#1e1e1e",
        font_size: int = 18,
        min_h: float | None = None,
    ) -> tuple[str, float, float, float, float]:
        """Return (id, x, y, w, h) with height auto-adjusted for label."""
        if min_h is None:
            min_h = h
        h = _estimate_height(label, w, font_size, min_h)
        rid = _id()
        tid = _id()
        self._track_bounds(x, y, w, h)
        self.elements.append(
            {
                "id": rid,
                "type": "rectangle",
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "angle": 0,
                "strokeColor": stroke,
                "backgroundColor": bg,
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "roughness": 1,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": {"type": 3},
                "seed": _seed(),
                "version": 1,
                "versionNonce": _seed(),
                "isDeleted": False,
                "boundElements": [{"type": "text", "id": tid}],
                "updated": 1,
                "link": None,
                "locked": False,
            }
        )
        self.elements.append(
            {
                "id": tid,
                "type": "text",
                "x": x + 12,
                "y": y + 12,
                "width": w - 24,
                "height": h - 24,
                "angle": 0,
                "strokeColor": stroke,
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "roughness": 1,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": None,
                "seed": _seed(),
                "version": 1,
                "versionNonce": _seed(),
                "isDeleted": False,
                "boundElements": None,
                "updated": 1,
                "link": None,
                "locked": False,
                "text": label,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": "center",
                "verticalAlign": "middle",
                "containerId": rid,
                "originalText": label,
                "lineHeight": 1.35,
            }
        )
        return rid, x, y, w, h

    def frame(self, x: float, y: float, w: float, h: float, label: str, *, behind: bool = False) -> None:
        """Light grouping rectangle. Use behind=True to render under other elements."""
        rid = _id()
        tid = _id()
        self._track_bounds(x, y, w, h)
        rect = {
            "id": rid,
            "type": "rectangle",
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "angle": 0,
            "strokeColor": "#868e96",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "dashed",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": {"type": 3},
            "seed": _seed(),
            "version": 1,
            "versionNonce": _seed(),
            "isDeleted": False,
            "boundElements": [{"type": "text", "id": tid}],
            "updated": 1,
            "link": None,
            "locked": False,
        }
        text = {
            "id": tid,
            "type": "text",
            "x": x + 16,
            "y": y + 8,
            "width": len(label) * 10,
            "height": 24,
            "angle": 0,
            "strokeColor": "#495057",
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "roundness": None,
            "seed": _seed(),
            "version": 1,
            "versionNonce": _seed(),
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
            "text": label,
            "fontSize": 16,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "containerId": rid,
            "originalText": label,
            "lineHeight": 1.25,
        }
        if behind:
            self.elements.insert(0, text)
            self.elements.insert(0, rect)
        else:
            self.elements.extend([rect, text])

    def arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        label: str | None = None,
        stroke: str = "#495057",
        label_offset_y: float = -18,
    ) -> None:
        dx, dy = x2 - x1, y2 - y1
        self.elements.append(
            {
                "id": _id(),
                "type": "arrow",
                "x": x1,
                "y": y1,
                "width": dx,
                "height": dy,
                "angle": 0,
                "strokeColor": stroke,
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "roughness": 0,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": {"type": 2},
                "seed": _seed(),
                "version": 1,
                "versionNonce": _seed(),
                "isDeleted": False,
                "boundElements": None,
                "updated": 1,
                "link": None,
                "locked": False,
                "points": [[0, 0], [dx, dy]],
                "lastCommittedPoint": None,
                "startBinding": None,
                "endBinding": None,
                "startArrowhead": None,
                "endArrowhead": "arrow",
            }
        )
        if label:
            lx = (x1 + x2) / 2 - len(label) * 4
            ly = (y1 + y2) / 2 + label_offset_y
            self._text_free(lx, ly, label, font_size=15, color=stroke)

    def arrow_down(self, cx: float, y_from: float, y_to: float, *, label: str | None = None) -> None:
        self.arrow(cx, y_from, cx, y_to, label=label, label_offset_y=-12)

    def arrow_right(self, x_from: float, x_to: float, cy: float, *, label: str | None = None) -> None:
        self.arrow(x_from, cy, x_to, cy, label=label)

    def title(self, text: str, *, y: float = 40) -> float:
        x = 80
        self._text_free(x, y, text, font_size=32, color="#1a365d", width=self.canvas_width - 160)
        return y + 56

    def subtitle(self, text: str, y: float) -> float:
        self._text_free(80, y, text, font_size=18, color="#495057", width=self.canvas_width - 160)
        return y + 36

    def note(self, y: float, text: str, *, bg: str = "#fff3bf", font_size: int = 16) -> float:
        x = 80
        w = self.canvas_width - 160
        h = _estimate_height(text, w, font_size, 70)
        self.box(x, y, w, h, text, bg=bg, font_size=font_size, min_h=h)
        return y + h + 40

    def _text_free(
        self,
        x: float,
        y: float,
        text: str,
        *,
        font_size: int = 16,
        color: str = "#1e1e1e",
        width: float = 400,
    ) -> None:
        h = _estimate_height(text, width, font_size, font_size + 8)
        self._track_bounds(x, y, width, h)
        self.elements.append(
            {
                "id": _id(),
                "type": "text",
                "x": x,
                "y": y,
                "width": width,
                "height": h,
                "angle": 0,
                "strokeColor": color,
                "backgroundColor": "transparent",
                "fillStyle": "solid",
                "strokeWidth": 1,
                "strokeStyle": "solid",
                "roughness": 0,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": None,
                "seed": _seed(),
                "version": 1,
                "versionNonce": _seed(),
                "isDeleted": False,
                "boundElements": None,
                "updated": 1,
                "link": None,
                "locked": False,
                "text": text,
                "fontSize": font_size,
                "fontFamily": 1,
                "textAlign": "left",
                "verticalAlign": "top",
                "containerId": None,
                "originalText": text,
                "lineHeight": 1.35,
            }
        )

    def row_boxes(
        self,
        y: float,
        items: list[tuple[str, str]],
        *,
        box_w: float = 220,
        box_h: float = 100,
        gap: float = 48,
        font_size: int = 17,
        center: bool = True,
    ) -> list[tuple[float, float, float, float]]:
        """Place boxes in a horizontal row; return list of (x,y,w,h)."""
        n = len(items)
        total_w = n * box_w + (n - 1) * gap
        x0 = (self.canvas_width - total_w) / 2 if center else 80
        rects: list[tuple[float, float, float, float]] = []
        x = x0
        for label, color in items:
            _, rx, ry, rw, rh = self.box(x, y, box_w, box_h, label, bg=color, font_size=font_size)
            rects.append((rx, ry, rw, rh))
            x += box_w + gap
        return rects

    def vertical_flow(
        self,
        start_y: float,
        steps: list[tuple[str, str]],
        *,
        box_w: float = 520,
        box_h: float = 88,
        gap: float = 56,
        font_size: int = 18,
    ) -> list[tuple[float, float, float, float]]:
        """Centered vertical pipeline with down arrows."""
        x = (self.canvas_width - box_w) / 2
        y = start_y
        rects: list[tuple[float, float, float, float]] = []
        for i, (label, color) in enumerate(steps):
            _, rx, ry, rw, rh = self.box(x, y, box_w, box_h, label, bg=color, font_size=font_size)
            rects.append((rx, ry, rw, rh))
            if i < len(steps) - 1:
                cx = x + box_w / 2
                next_y = y + rh + gap
                self.arrow_down(cx, y + rh + 4, next_y - 4)
                y = next_y
            else:
                y += rh
        return rects

    def section_header(self, y: float, text: str, *, number: str | None = None) -> float:
        """Large section divider for multi-diagram canvases."""
        label = f"{number}  {text}" if number else text
        x = 60
        w = self.canvas_width - 120
        h = 56
        self._track_bounds(x, y, w, h)
        self.elements.append(
            {
                "id": _id(),
                "type": "rectangle",
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "angle": 0,
                "strokeColor": "#1a365d",
                "backgroundColor": "#e7f5ff",
                "fillStyle": "solid",
                "strokeWidth": 2,
                "strokeStyle": "solid",
                "roughness": 0,
                "opacity": 100,
                "groupIds": [],
                "frameId": None,
                "roundness": {"type": 3},
                "seed": _seed(),
                "version": 1,
                "versionNonce": _seed(),
                "isDeleted": False,
                "boundElements": None,
                "updated": 1,
                "link": None,
                "locked": False,
            }
        )
        self._text_free(x + 20, y + 14, label, font_size=24, color="#1a365d", width=w - 40)
        return y + h + 32

    def save(self, path: Path, *, fit_viewport: bool = True, zoom: float | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        pad = 48
        if fit_viewport and zoom is None:
            viewport_w, viewport_h = 1280, 900
            content_w = max(self._max_x + pad, self.canvas_width)
            content_h = self._max_y + pad
            zoom_val = min(viewport_w / content_w, viewport_h / content_h)
            zoom_val = max(0.55, min(zoom_val, 1.15))
        else:
            zoom_val = zoom if zoom is not None else 0.8
        payload = {
            "type": "excalidraw",
            "version": 2,
            "source": "https://excalidraw.com",
            "elements": self.elements,
            "appState": {
                "gridSize": 20,
                "viewBackgroundColor": "#ffffff",
                "scrollX": pad,
                "scrollY": pad,
                "zoom": {"value": round(zoom_val, 2)},
            },
            "files": {},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
