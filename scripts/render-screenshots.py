#!/usr/bin/env python3
"""Renders the text screenshots of packs into screenshots/<pack>/: the pack's files as
they are, set in a monospace font on the Workshop's dark background. Nothing is drawn
that is not in the repository; `author` and `source` lines are left out of skills.

    scripts/render-screenshots.py

Needs Pillow with WebP. Uses Menlo or SF Mono when present, else Pillow's own font.
"""

import pathlib
import textwrap

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIZE = (1600, 1000)
MARGIN = 72
BACKGROUND = "#0f1115"
TEXT = "#d6d9e0"
DIM = "#7a8191"
ACCENT = "#e0a458"
FONTS = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf"]
FONT_SIZE = 24
LINE = 36
WIDTH = 96
# Personal or provenance fields kept out of a picture; they stay in the files.
HIDDEN = ("author:", "source:")


def font(size):
    for path in FONTS:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def wrapped(lines):
    out = []
    for line in lines:
        indent = len(line) - len(line.lstrip())
        out += textwrap.wrap(line, WIDTH, subsequent_indent=" " * (indent + 2)) or [""]
    return out


def render(title, lines, out):
    image = Image.new("RGB", SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, MARGIN - 8), title, font=font(FONT_SIZE), fill=ACCENT)
    draw.line((MARGIN, MARGIN + 36, SIZE[0] - MARGIN, MARGIN + 36), fill=DIM, width=1)
    body = font(FONT_SIZE)
    rows = (SIZE[1] - MARGIN * 2 - 60) // LINE
    for row, line in enumerate(wrapped(lines)[:rows]):
        key, colon, rest = line.partition(":")
        y = MARGIN + 60 + row * LINE
        if colon and key.strip() and " " not in key.strip() and not line.startswith(" "):
            draw.text((MARGIN, y), key + colon, font=body, fill=ACCENT)
            draw.text((MARGIN + body.getlength(key + colon), y), rest, font=body, fill=TEXT)
        else:
            draw.text((MARGIN, y), line, font=body, fill=DIM if line.startswith("#") else TEXT)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "WEBP", lossless=True, method=6)
    print(f"{out.relative_to(ROOT)}: {out.stat().st_size} bytes")


def file_lines(path, limit=60):
    lines = path.read_text().splitlines()[:limit]
    return [line for line in lines if not line.startswith(HIDDEN)]


def skills(pack):
    """Each skill of a pack with the first sentence of its description."""
    manifest = yaml.safe_load((ROOT / "packs" / pack / "pack.yml").read_text())
    lines = []
    for item in manifest["items"]:
        front = (ROOT / "packs" / pack / item / "SKILL.md").read_text().split("---")[1]
        sentence = yaml.safe_load(front)["description"].split(". ")[0].rstrip(".") + "."
        lines += [f"{item}/", "  " + sentence, ""]
    return lines


def main():
    shots = ROOT / "screenshots"
    engineering = ROOT / "packs" / "duskcode-engineering"
    render("packs/duskcode-engineering/pack.yml", file_lines(engineering / "pack.yml"),
           shots / "duskcode-engineering" / "1-pack.webp")
    render("packs/duskcode-engineering/*/SKILL.md: what each is for", skills("duskcode-engineering"),
           shots / "duskcode-engineering" / "2-skills.webp")
    render("packs/duskcode-engineering/systematic-debugging/SKILL.md",
           file_lines(engineering / "systematic-debugging" / "SKILL.md"),
           shots / "duskcode-engineering" / "3-debugging.webp")
    security = ROOT / "packs" / "duskcode-security"
    render("packs/duskcode-security/*/SKILL.md: what each is for", skills("duskcode-security"),
           shots / "duskcode-security" / "1-skills.webp")
    render("packs/duskcode-security/web-security-assessment/SKILL.md",
           file_lines(security / "web-security-assessment" / "SKILL.md"),
           shots / "duskcode-security" / "2-web.webp")


if __name__ == "__main__":
    main()
