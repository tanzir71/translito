"""Build the supplied SVG mark with Pillow at 4x resolution (no SVG runtime)."""
import argparse
import math
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def mark(size, *, masters=ROOT / "branding"):
    svg = ET.parse(masters / ("translito-mark-small.svg" if size <= 40 else "translito-mark.svg")).getroot()
    scale = size * 4 / 400
    canvas = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(canvas)
    path = svg.find("{*}path")
    x, y, radius, _, _, _, _, endx, endy, tail = map(float, re.findall(r"[\d.]+", path.attrib["d"]))
    dx, dy = endx - x, endy - y
    distance = math.hypot(dx, dy)
    height = math.sqrt(radius ** 2 - distance ** 2 / 4)
    cx, cy = (x + endx) / 2 - dy / distance * height, (y + endy) / 2 + dx / distance * height
    start, end = math.atan2(y - cy, x - cx), math.atan2(endy - cy, endx - cx)
    while end >= start:
        end -= 2 * math.pi
    points = [(scale * (cx + radius * math.cos(start + (end - start) * i / 720)),
               scale * (cy + radius * math.sin(start + (end - start) * i / 720))) for i in range(721)]
    points += [(endx * scale, tail * scale), (x * scale, y * scale)]
    draw.polygon(points, fill=path.attrib["fill"])
    width = round(float(path.attrib["stroke-width"]) * scale)
    draw.line(points, fill=path.attrib["stroke"], width=width, joint="curve")
    for rect in svg.findall("{*}rect"):
        a = rect.attrib
        rx, ry, w, h = (float(a[k]) * scale for k in ("x", "y", "width", "height"))
        draw.rounded_rectangle((rx, ry, rx + w, ry + h), radius=float(a["rx"]) * scale, fill=a["fill"])
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def build_windows(root=ROOT):
    (root / "installer").mkdir(parents=True, exist_ok=True)
    frames = [mark(size) for size in ICO_SIZES]
    frames[-1].save(root / "installer/Translito.ico", sizes=[(n, n) for n in ICO_SIZES], append_images=frames[:-1])
    tray = root / "engines/data/tray"
    tray.mkdir(parents=True, exist_ok=True)
    for size in (32, 64):
        for state, color in (("idle", None), ("listening", "#30d158"), ("paused", "#ff9f0a")):
            icon = mark(size * 4)
            if color:
                d = ImageDraw.Draw(icon)
                d.ellipse((size * 2.7, size * 2.7, size * 3.7, size * 3.7), fill=color, outline="#0b0b0c", width=max(1, size // 8))
            icon.resize((size, size), Image.Resampling.LANCZOS).save(tray / f"{state}-{size}.png")
    web = root / "website/static"
    web.mkdir(parents=True, exist_ok=True)
    mark(512).save(web / "translito-icon.png")
    shutil.copyfile(ROOT / "branding/translito-mark.svg", web / "favicon.svg")


def build_macos(root=ROOT):
    tile = Image.new("RGBA", (4096, 4096))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((400, 400, 3696, 3696), radius=720, fill="#0b0b0c")
    glyph = mark(2400)
    tile.alpha_composite(glyph, (848, 848))
    tile = tile.resize((1024, 1024), Image.Resampling.LANCZOS)
    folder = root / "native_macos/branding"
    folder.mkdir(parents=True, exist_ok=True)
    tile.save(folder / "Translito-AppIcon-1024.png")
    tile.save(folder / "Translito.icns", sizes=[(n, n) for n in (16, 32, 64, 128, 256, 512, 1024)])
    assets = root / "native_macos/DesktopAudioTranslator/DesktopAudioTranslator/Assets.xcassets/AppIcon.appiconset"
    assets.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for multiple in (1, 2):
            name = f"icon_{size}x{size}" + ("@2x" if multiple == 2 else "") + ".png"
            resized = tile.resize((size * multiple,) * 2, Image.Resampling.LANCZOS)
            # Lanczos rings at very small sizes; keep the outer margin truly clear.
            d = ImageDraw.Draw(resized)
            d.rectangle((0, 0, resized.width - 1, resized.height - 1), outline=(0, 0, 0, 0))
            resized.save(assets / name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--macos", action="store_true")
    options = parser.parse_args()
    build_macos() if options.macos else build_windows()
