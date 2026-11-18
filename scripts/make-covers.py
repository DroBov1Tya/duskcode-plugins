#!/usr/bin/env python3
"""Writes the Workshop covers as SVG into covers/src/. Original geometry only, generic
fonts, and no name, mark or colours of anybody else: a pack of somebody else's skills is
named for what it does. The covers of web-builder-skills, dev-workflow-skills and
gpu-computing-skills are not rendered yet (the maintainer draws them); until covers/ has
them, they are listed without a cover and shown with the plain placeholder.

    scripts/make-covers.py && scripts/render-covers.sh
"""

import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "covers" / "src"
W, H = 1200, 630
BG, INK, MUTED = "#0c0e13", "#f4f5f7", "#8a90a0"

# name: (title, small label, accent, shape)
COVERS = {
    "duskcode-engineering": ("Engineering", "SKILL PACK / DUSKCODE", "#f5a524", "stairs"),
    "duskcode-security": ("Security", "SKILL PACK / DUSKCODE", "#ff4d6d", "shield"),
    "duskcode-agents": ("Agents", "AGENT PACK / DUSKCODE", "#9b8cff", "orbit"),
    "ios-simulator": ("ios-simulator", "PLUGIN / DEVICES", "#38bdf8", "phone"),
    "vphone": ("vphone", "PLUGIN / DEVICES", "#e879f9", "phone2"),
    "telegram": ("telegram", "PLUGIN / CHAT", "#60a5fa", "bubbles"),
}


def shapes(kind, c):
    x0 = 700  # the art lives on the right half
    if kind == "stairs":
        return "".join(
            f'<rect x="{x0 + 40 + i * 90}" y="{470 - i * 80}" width="80" height="{160 + i * 80}" fill="{c}" opacity="{0.25 + i * 0.15}"/>'
            for i in range(5)
        )
    if kind == "shield":
        return (
            f'<path d="M900 110 L1080 170 V340 Q1080 470 900 540 Q720 470 720 340 V170 Z" fill="none" stroke="{c}" stroke-width="14"/>'
            f'<path d="M900 190 L1010 228 V340 Q1010 420 900 466 Z" fill="{c}" opacity="0.85"/>'
            f'<path d="M900 190 L790 228 V340 Q790 420 900 466 Z" fill="{c}" opacity="0.35"/>'
        )
    if kind == "orbit":
        dots = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>' for x, y, r in [(900, 135, 22), (1060, 330, 16), (760, 420, 26), (950, 505, 12)])
        return (
            f'<circle cx="900" cy="320" r="190" fill="none" stroke="{c}" stroke-width="6" opacity="0.5"/>'
            f'<circle cx="900" cy="320" r="120" fill="none" stroke="{c}" stroke-width="6" opacity="0.8"/>'
            f'<circle cx="900" cy="320" r="46" fill="{c}"/>' + dots
        )
    if kind == "arches":
        return "".join(
            f'<path d="M{x0 + i * 100} 520 V{300 - i * 20} A50 50 0 0 1 {x0 + i * 100 + 100} {300 - i * 20} V520 Z" fill="{c}" opacity="{0.3 + i * 0.2}"/>'
            for i in range(4)
        )
    if kind == "rings":
        return "".join(
            f'<circle cx="{900 + dx}" cy="{320 + dy}" r="120" fill="none" stroke="{c}" stroke-width="14" opacity="{o}"/>'
            for dx, dy, o in [(-70, -50, 0.9), (70, -50, 0.65), (0, 70, 0.4)]
        )
    if kind == "slabs":
        return "".join(
            f'<polygon points="{x0 + 40 + i * 30},{150 + i * 110} {x0 + 360 + i * 30},{150 + i * 110} {x0 + 400 + i * 30},{200 + i * 110} {x0 + 80 + i * 30},{200 + i * 110}" fill="{c}" opacity="{0.9 - i * 0.22}"/>'
            for i in range(4)
        )
    if kind == "phone":
        return (
            f'<rect x="770" y="90" width="260" height="450" rx="40" fill="none" stroke="{c}" stroke-width="12"/>'
            f'<rect x="800" y="130" width="200" height="300" rx="14" fill="{c}" opacity="0.2"/>'
            f'<circle cx="900" cy="480" r="22" fill="none" stroke="{c}" stroke-width="8"/>'
            f'<rect x="850" y="106" width="100" height="10" rx="5" fill="{c}"/>'
            f'<polygon points="840,180 960,260 840,340" fill="{c}"/>'
        )
    if kind == "phone2":
        return (
            f'<rect x="760" y="120" width="230" height="400" rx="40" fill="none" stroke="{c}" stroke-width="12" stroke-dasharray="26 14"/>'
            f'<rect x="830" y="90" width="230" height="400" rx="40" fill="{c}" opacity="0.28"/>'
            f'<circle cx="945" cy="290" r="64" fill="{c}"/>'
        )
    # bubbles
    return (
        f'<path d="M740 130 H1000 Q1040 130 1040 170 V300 Q1040 340 1000 340 H850 L790 400 V340 H740 Q700 340 700 300 V170 Q700 130 740 130 Z" fill="{c}"/>'
        f'<path d="M1100 330 H1000 V400 H1090 L1130 450 V400 H1150 V360 Q1150 330 1100 330 Z" fill="{c}" opacity="0.4"/>'
        f'<rect x="740" y="180" width="200" height="14" rx="7" fill="{BG}"/><rect x="740" y="220" width="150" height="14" rx="7" fill="{BG}"/>'
        f'<rect x="740" y="260" width="230" height="14" rx="7" fill="{BG}"/>'
    )


def cover(name, title, label, accent, shape):
    size = 120 if len(title) <= 8 else 100 if len(title) <= 11 else 92
    grid = "".join(f'<path d="M{x} 0 V{H}" stroke="#ffffff" stroke-opacity="0.04"/>' for x in range(0, W, 60))
    grid += "".join(f'<path d="M0 {y} H{W}" stroke="#ffffff" stroke-opacity="0.04"/>' for y in range(0, H, 60))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<rect width="{W}" height="{H}" fill="{BG}"/>
{grid}
<rect x="0" y="0" width="18" height="{H}" fill="{accent}"/>
{shapes(shape, accent)}
<g font-family="Helvetica Neue, Helvetica, Arial, sans-serif">
<text x="70" y="96" font-size="26" font-weight="700" letter-spacing="6" fill="{accent}">{label}</text>
<text x="70" y="{H - 200}" font-size="{size}" font-weight="800" fill="{INK}">{title}</text>
<text x="70" y="{H - 70}" font-size="28" font-weight="600" letter-spacing="8" fill="{MUTED}">DUSKCODE WORKSHOP</text>
</g>
</svg>
"""


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, spec in COVERS.items():
        (OUT / f"{name}.svg").write_text(cover(name, *spec))
    print(f"wrote {len(COVERS)} covers into {OUT}")
