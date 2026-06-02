"""Generate the Open Graph share image (1200x630) shown in link previews
(iMessage, Slack, etc.).

Run from project root:
    uv run --group dev python scripts/gen_og.py

Writes: static/og.png

Cohesive with the cover / favicon: warm sunset gradient, a white play tile,
the Feed Me wordmark, and a tagline. Production never runs this — the PNG is
served statically. Re-run + commit the script and PNG together on change.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent.parent / "static" / "og.png"
W, H = 1200, 630
SS = 2  # supersample for crisp text/edges

GRAD_TOP = (0xF6, 0xE3, 0xCE)
GRAD_MID = (0xE8, 0xB2, 0x89)
GRAD_BOT = (0xC4, 0x69, 0x4A)
INK = (0x2D, 0x18, 0x10)
SUBINK = (0x6E, 0x44, 0x30)
TILE = (0xB0, 0x4A, 0x00)
GLYPH = (0xFF, 0xF3, 0xEA)

FONT_BOLD = [
    ("/System/Library/Fonts/Helvetica.ttc", 1),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]
FONT_REG = [
    ("/System/Library/Fonts/Helvetica.ttc", 0),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]


def _interp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _font(cands, size):
    for path, idx in cands:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except (IOError, OSError):
            continue
    raise RuntimeError("Couldn't find a system font; edit FONT_* lists.")


def _gradient(w, h):
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / (h - 1)
        px[0, y] = _interp(GRAD_TOP, GRAD_MID, t * 2) if t < 0.5 else _interp(GRAD_MID, GRAD_BOT, (t - 0.5) * 2)
    return col.resize((w, h))


def main():
    w, h = W * SS, H * SS
    img = _gradient(w, h).convert("RGBA")
    d = ImageDraw.Draw(img)

    # Play tile (matches the favicon), centered near the top.
    tile = int(132 * SS)
    tx = (w - tile) // 2
    ty = int(116 * SS)
    d.rounded_rectangle([tx, ty, tx + tile, ty + tile], radius=int(tile * 0.235), fill=TILE)
    cx, cy = tx + tile * 0.56, ty + tile * 0.5
    tw, th = tile * 0.26, tile * 0.30
    d.polygon([(cx - tw, cy - th), (cx - tw, cy + th), (cx + tw, cy)], fill=GLYPH)

    # Wordmark.
    bold = _font(FONT_BOLD, int(128 * SS))
    word = "Feed Me"
    wb = d.textbbox((0, 0), word, font=bold)
    wy = ty + tile + int(56 * SS)
    d.text(((w - (wb[2] - wb[0])) // 2 - wb[0], wy), word, font=bold, fill=INK)

    # Tagline.
    reg = _font(FONT_REG, int(38 * SS))
    tag = "Your articles read to you in a private podcast feed"
    tb = d.textbbox((0, 0), tag, font=reg)
    tyy = wy + (wb[3] - wb[1]) + int(44 * SS)
    d.text(((w - (tb[2] - tb[0])) // 2 - tb[0], tyy), tag, font=reg, fill=SUBINK)

    img.convert("RGB").resize((W, H), Image.LANCZOS).save(OUT, quality=90)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
