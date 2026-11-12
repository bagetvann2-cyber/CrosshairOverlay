import numpy as np
import zlib
import struct
import os

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "crosshairs")


def write_png(path, rgba):
    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))
    compressed = zlib.compress(raw, 9)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    idat = chunk(b"IDAT", compressed)
    iend = chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(signature + ihdr + idat + iend)


def make_dot(size=64):
    img = np.zeros((size, size, 4), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    r = max(2, size // 16)
    for y in range(size):
        for x in range(size):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2:
                img[y, x] = [255, 255, 255, 255]
    return img


def make_cross(size=64):
    img = np.zeros((size, size, 4), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    thickness = max(1, size // 32)
    gap = max(2, size // 16)
    arm = size // 4

    for t in range(-thickness, thickness + 1):
        # horizontal arms
        for x in range(cx + gap, cx + gap + arm):
            if 0 <= cy + t < size and 0 <= x < size:
                img[cy + t, x] = [255, 255, 255, 255]
        for x in range(cx - gap - arm, cx - gap):
            if 0 <= cy + t < size and 0 <= x < size:
                img[cy + t, x] = [255, 255, 255, 255]
        # vertical arms
        for y in range(cy + gap, cy + gap + arm):
            if 0 <= y < size and 0 <= cx + t < size:
                img[y, cx + t] = [255, 255, 255, 255]
        for y in range(cy - gap - arm, cy - gap):
            if 0 <= y < size and 0 <= cx + t < size:
                img[y, cx + t] = [255, 255, 255, 255]
    return img


def make_circle(size=64):
    img = np.zeros((size, size, 4), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    radius = size // 3
    thickness = max(1, size // 32)
    for y in range(size):
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if radius - thickness <= d <= radius + thickness:
                img[y, x] = [255, 255, 255, 255]
    return img


def make_circle_cross(size=64):
    img = np.zeros((size, size, 4), dtype=np.uint8)
    cx, cy = size // 2, size // 2
    radius = size // 3
    thickness = max(1, size // 32)
    gap = max(2, size // 16)
    arm = size // 5

    # circle
    for y in range(size):
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if radius - thickness <= d <= radius + thickness:
                img[y, x] = [255, 255, 255, 255]

    # cross arms (outside circle)
    for t in range(-thickness, thickness + 1):
        for x in range(cx + radius + gap, cx + radius + gap + arm):
            if 0 <= cy + t < size and 0 <= x < size:
                img[cy + t, x] = [255, 255, 255, 255]
        for x in range(cx - radius - gap - arm, cx - radius - gap):
            if 0 <= cy + t < size and 0 <= x < size:
                img[cy + t, x] = [255, 255, 255, 255]
        for y in range(cy + radius + gap, cy + radius + gap + arm):
            if 0 <= y < size and 0 <= cx + t < size:
                img[y, cx + t] = [255, 255, 255, 255]
        for y in range(cy - radius - gap - arm, cy - radius - gap):
            if 0 <= y < size and 0 <= cx + t < size:
                img[y, cx + t] = [255, 255, 255, 255]
    return img


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    write_png(os.path.join(OUTPUT_DIR, "dot.png"), make_dot(64))
    write_png(os.path.join(OUTPUT_DIR, "cross.png"), make_cross(64))
    write_png(os.path.join(OUTPUT_DIR, "circle.png"), make_circle(64))
    write_png(os.path.join(OUTPUT_DIR, "circle_cross.png"), make_circle_cross(64))
    print("Done! Generated: dot.png, cross.png, circle.png, circle_cross.png")
