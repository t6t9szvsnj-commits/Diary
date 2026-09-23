"""Рисует иконки приложения без сторонних библиотек: раскрытая тетрадь
на синем фоне. Запускать вручную, если захочется поменять иконку."""

import struct
import sys
import zlib
from pathlib import Path

BG = (59, 91, 219)
PAGE = (255, 255, 255)
LINE = (190, 200, 235)
SPINE = (40, 62, 160)


def pixel(x, y):
    # Всё в долях от стороны, чтобы одна функция рисовала любой размер.
    # Поля широкие: iOS и Android обрезают углы и края иконки.
    if not (0.24 <= y <= 0.76):
        return BG
    if 0.495 <= x <= 0.505:
        return SPINE
    for left, right in ((0.2, 0.495), (0.505, 0.8)):
        if left <= x <= right:
            inner = left + 0.05 <= x <= right - 0.05
            for ly in (0.36, 0.45, 0.54, 0.63):
                if inner and ly <= y <= ly + 0.018:
                    return LINE
            return PAGE
    return BG


def png(size):
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel((x + 0.5) / size, (y + 0.5) / size)) for x in range(size))
        for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "app")
    for size in (180, 512):
        (out / f"icon-{size}.png").write_bytes(png(size))
