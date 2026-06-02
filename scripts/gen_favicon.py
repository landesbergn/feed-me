"""Generate the Feed Me favicon set (warm rounded tile + play glyph).

Run from project root:
    uv run --group dev python scripts/gen_favicon.py

Writes:
    static/favicon.ico          (16, 32, 48 — browser tabs)
    static/favicon-32.png       (modern <link rel=icon>)
    static/apple-touch-icon.png (180 — iOS home screen)
    static/icon-512.png         (master / PWA)

Cohesive with static/cover.jpg: warm sunset gradient + a single white
play triangle (the same "play glyph" motif as the cover). Production
never executes this — the images are served as static files. Re-run and
commit the script + outputs together when the mark changes.
"""
from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).parent.parent / "static"

SS = 8           # supersample factor for crisp edges, downsampled at save
SIZE = 512       # master logical size
RADIUS_FRAC = 0.235   # rounded-corner radius as fraction of size

# Warm sunset, tied to cover.jpg but deepened for legibility at 16px.
GRAD_TOP = (0xE8, 0xB2, 0x89)   # #E8B289  (cover mid)
GRAD_BOT = (0xB0, 0x4A, 0x00)   # #B04A00  (brand accent)
GLYPH = (0xFF, 0xF3, 0xEA)      # warm white


def _interp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _gradient(size):
    """Vertical 2-stop gradient, top→bottom."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        row = _interp(GRAD_TOP, GRAD_BOT, y / (size - 1))
        for x in range(size):
            px[x, y] = row
    return img


def _rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def _play_triangle(draw, size):
    """A right-pointing play triangle, optically centered (nudged right)."""
    w = size * 0.30          # half-width of the triangle bounding box
    h = size * 0.34          # half-height
    cx = size * 0.535        # optical center sits right of true center
    cy = size * 0.5
    # Slightly rounded tip via joint='curve' on a thick-ish outline-free polygon.
    pts = [
        (cx - w, cy - h),
        (cx - w, cy + h),
        (cx + w, cy),
    ]
    draw.polygon(pts, fill=GLYPH)


def make_master():
    big = SIZE * SS
    radius = int(big * RADIUS_FRAC)

    base = _gradient(big)
    glyph_layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph_layer)
    _play_triangle(gd, big)

    composed = base.convert("RGBA")
    composed.alpha_composite(glyph_layer)

    mask = _rounded_mask(big, radius)
    composed.putalpha(mask)

    return composed.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    master = make_master()
    master.save(STATIC / "icon-512.png")
    master.resize((180, 180), Image.LANCZOS).save(STATIC / "apple-touch-icon.png")
    master.resize((32, 32), Image.LANCZOS).save(STATIC / "favicon-32.png")
    master.save(
        STATIC / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    print("Wrote: icon-512.png, apple-touch-icon.png, favicon-32.png, favicon.ico")


if __name__ == "__main__":
    main()
