"""Build the supplied SVG mark with Pillow at 4x resolution (no SVG runtime)."""
import argparse
import math
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ICO_SIZES = (16, 20, 24, 28, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 128, 256)
TRAY_SIZES = (16, 20, 24, 28, 32, 40, 48)


def mark(size, *, masters=ROOT / "branding", cut_size=None, supersampled=False):
    svg = ET.parse(masters / ("translito-mark-small.svg" if (cut_size or size) <= 40 else "translito-mark.svg")).getroot()
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
    return canvas if supersampled else canvas.resize((size, size), Image.Resampling.LANCZOS)


def tray_frame(size, state):
    canvas = mark(size, cut_size=16, supersampled=True)
    color = {"idle": None, "listening": "#30d158", "paused": "#ff9f0a"}[state]
    if color:
        ImageDraw.Draw(canvas).ellipse((size*2.7, size*2.7, size*3.7, size*3.7),
            fill=color, outline="#0b0b0c", width=max(1, round(size/8)))
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def build_windows(root=ROOT):
    (root / "installer").mkdir(parents=True, exist_ok=True)
    frames = [mark(size) for size in ICO_SIZES]
    frames[-1].save(root / "installer/Translito.ico", sizes=[(n, n) for n in ICO_SIZES], append_images=frames[:-1])
    tray = root / "engines/data/tray"
    tray.mkdir(parents=True, exist_ok=True)
    for state in ("idle", "listening", "paused"):
        frames = [tray_frame(size, state) for size in TRAY_SIZES]
        frames[-1].save(tray / f"{state}.ico", sizes=[(n,n) for n in TRAY_SIZES], append_images=frames[:-1])
        for size in (32, 64):
            tray_frame(size, state).save(tray / f"{state}-{size}.png")
    from app_identity import APP_USER_MODEL_ID
    (root / "installer/app_identity.iss").write_text(f'#define AppUserModelID "{APP_USER_MODEL_ID}"\n', encoding="utf-8")
    web = root / "website/static"
    web.mkdir(parents=True, exist_ok=True)
    mark(512).save(web / "translito-icon.png")
    shutil.copyfile(ROOT / "branding/translito-mark.svg", web / "favicon.svg")


def contact_sheet(root=ROOT):
    sheet = Image.new("RGB", (720, 390), "#1f1f1f")
    draw = ImageDraw.Draw(sheet)
    draw.text((20, 14), "Translito 2.0.1 - native pixel sizes (old / new)", fill="white")
    for row, (title, sizes) in enumerate((("Tray", (16,20,24,32)), ("Taskbar", (24,30,36,48)))):
        top = 55 + row*160
        draw.text((20, top), title, fill="white")
        for column, size in enumerate(sizes):
            left = 125 + column*140
            old = mark(64*4, cut_size=64).resize((64,64), Image.Resampling.LANCZOS).resize((size,size), Image.Resampling.LANCZOS)
            new = tray_frame(size, "idle") if row == 0 else mark(size)
            sheet.paste(old, (left,top+25), old)
            sheet.paste(new, (left+60,top+25), new)
            draw.text((left,top+83), f"{size}px  old / new", fill="#b1b1b6")
    target = root / "docs/quality/icons-2.0.1.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    return target


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
    parser.add_argument("--sheet", action="store_true")
    options = parser.parse_args()
    build_macos() if options.macos else build_windows()
    if options.sheet:
        contact_sheet()
