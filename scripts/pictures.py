"""The rules duskcode's reader applies to the pictures of a list (covers and
screenshots, projects/core/src/plugins/store/index.rs and picture.rs), shared by
publish.py and check-index.py."""

import re

COVER_LIMIT = 512 * 1024
SCREENSHOT_LIMIT = 1024 * 1024
MAX_SCREENSHOTS = 8
MAX_CAPTION = 120
# Width and height in pixels, read from the header: a small file can still unpack into a
# huge picture. A cover is drawn at 1200x630, a screenshot at 1600x1000; twice that is kept.
COVER_PIXELS = (2400, 1260)
SCREENSHOT_PIXELS = (3200, 2000)
PART = re.compile(r"^[A-Za-z0-9._-]+$")
MIME = {".png": "image/png", ".webp": "image/webp"}


def plain_path(path):
    """Relative, at most 200 bytes, parts of A-Z a-z 0-9 . _ - and never . or .."""
    parts = path.split("/")
    return 0 < len(path) <= 200 and all(PART.match(p) and p not in (".", "..") for p in parts)


def mime(path):
    return next((m for ext, m in MIME.items() if path.endswith(ext)), None)


def sniff(data):
    """The type by the first bytes, as the core trusts it over the name."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def pixels(data):
    """(width, height) from a PNG or WebP header, without decoding; None when unreadable."""
    number = lambda part: int.from_bytes(part, "little")
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8X":
        return number(data[24:27]) + 1, number(data[27:30]) + 1
    if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        return number(data[26:28]) & 0x3FFF, number(data[28:30]) & 0x3FFF
    if kind == b"VP8L" and data[20] == 0x2F:
        bits = number(data[21:25])
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def caption_ok(text):
    """One plain line: not empty or padded, at most 120 characters, no control
    characters and no bidi overrides or isolates."""
    bad = lambda c: ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0x202A <= ord(c) <= 0x202E \
        or 0x2066 <= ord(c) <= 0x2069
    return isinstance(text, str) and text.strip() == text and text != "" \
        and len(text) <= MAX_CAPTION and not any(bad(c) for c in text)


def problem(path, data, limit):
    """Why the picture `data` at `path` would be refused, or None."""
    if not plain_path(path):
        return "the path is not a plain relative path"
    if mime(path) is None:
        return "it is not a .png or .webp"
    if not 1 <= len(data) <= limit:
        return f"it is {len(data)} bytes, not 1 to {limit}"
    if sniff(data) != mime(path):
        return "its bytes are not the picture its name says"
    most = COVER_PIXELS if limit == COVER_LIMIT else SCREENSHOT_PIXELS
    size = pixels(data)
    if size is None or not (1 <= size[0] <= most[0] and 1 <= size[1] <= most[1]):
        return f"it is {size} pixels, not within {most[0]}x{most[1]}"
    return None
