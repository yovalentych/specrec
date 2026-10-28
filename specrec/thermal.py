"""Receipts on a small thermal printer (58 / 80 mm, ESC/POS).

The text is drawn as a picture (so Cyrillic and symbols like ± ² ₂ print on any printer,
whatever code pages it knows) and sent with the ESC/POS raster command GS v 0.
Transport: a serial port — a Bluetooth printer with the classic serial profile (SPP) appears
on macOS as /dev/cu.<name> after pairing, on Linux as /dev/rfcomm0, on Windows as COMn.
Every receipt is also saved as PNG (preview / no printer).
"""
from __future__ import annotations

import time

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

WIDTHS = {"58 мм (384 точки)": 384, "80 мм (576 точок)": 576}


def render(lines: list[tuple[str, str]], width: int = 384) -> QImage:
    """lines: [(style, text)], style: 'title' | 'bold' | 'text' | 'small' | 'rule' | 'gap'."""
    sizes = {"title": 30, "bold": 22, "text": 21, "small": 17}
    fam = "Arial"
    # measure
    tmp = QImage(width, 10, QImage.Format_RGB32)
    p = QPainter(tmp)
    heights = []
    for style, text in lines:
        if style == "rule":
            heights.append(14)
            continue
        if style == "gap":
            heights.append(12)
            continue
        f = QFont(fam)
        f.setPixelSize(sizes.get(style, 21))
        f.setBold(style in ("title", "bold"))
        p.setFont(f)
        r = p.boundingRect(QRect(0, 0, width - 8, 2000), Qt.TextWordWrap, text)
        heights.append(r.height() + 4)
    p.end()
    img = QImage(width, sum(heights) + 40, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    y = 8
    for (style, text), h in zip(lines, heights):
        if style == "rule":
            p.drawLine(0, y + 6, width, y + 6)
        elif style != "gap":
            f = QFont(fam)
            f.setPixelSize(sizes.get(style, 21))
            f.setBold(style in ("title", "bold"))
            p.setFont(f)
            align = Qt.AlignHCenter if style == "title" else Qt.AlignLeft
            p.drawText(QRect(4, y, width - 8, h), align | Qt.TextWordWrap, text)
        y += h
    p.end()
    return img


def escpos_raster(img: QImage) -> bytes:
    """ESC/POS: init + GS v 0 raster image (in bands of 255 rows) + feed + partial cut."""
    w, h = img.width(), img.height()
    wb = (w + 7) // 8
    out = bytearray(b"\x1b@")
    band = 255
    for y0 in range(0, h, band):
        rows = min(band, h - y0)
        out += b"\x1dv0\x00" + bytes([wb & 0xFF, wb >> 8, rows & 0xFF, rows >> 8])
        for y in range(y0, y0 + rows):
            line = bytearray(wb)
            for x in range(w):
                if QColor(img.pixel(x, y)).lightness() < 128:
                    line[x >> 3] |= 0x80 >> (x & 7)
            out += line
    out += b"\n\n\n\x1dV\x01"
    return bytes(out)


def send(port: str, data: bytes, baud: int = 9600):
    """Write to the printer in small chunks (Bluetooth printers have small buffers)."""
    import serial
    with serial.Serial(port, baud, timeout=2, write_timeout=20) as s:
        for i in range(0, len(data), 512):
            s.write(data[i:i + 512])
            s.flush()
            time.sleep(0.03)
        time.sleep(0.5)


def candidate_ports() -> list[str]:
    """Serial ports that may be a printer (everything except the instrument and system ports)."""
    out = []
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            d = p.device
            if any(x in d for x in ("debug-console", "wlan-debug", "Bluetooth-Incoming-Port")) or d.startswith("/dev/tty."):
                continue
            out.append(d)
    except Exception:
        pass
    import glob
    for d in glob.glob("/dev/rfcomm*"):
        if d not in out:
            out.append(d)
    return out
