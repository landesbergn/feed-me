"""Generate the Feed Me cover art (3000x3000 JPG, Sunset direction).

Run from project root:
    uv run --group dev python scripts/gen_cover.py

Writes: static/cover.jpg

Re-run when the design changes; commit both this script and the new
JPG output together. Production never executes this — the JPG is
served as a static file.

Font note: the wordmark uses macOS Helvetica Bold. On Linux/Windows
edit FONT_CANDIDATES below to point at a comparable bold sans.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path(__file__).parent.parent / "static" / "cover.jpg"
SIZE = 3000
PAD = 280

GRAD_TOP = (0xF3, 0xDC, 0xC1)  # #F3DCC1
GRAD_MID = (0xE8, 0xB2, 0x89)  # #E8B289
GRAD_BOT = (0xC9, 0x70, 0x56)  # #C97056
INK = (0x2D, 0x18, 0x10)        # #2D1810
CREAM = (0xF3, 0xDC, 0xC1)      # #F3DCC1

FONT_SIZE = 470
LINE_HEIGHT = int(FONT_SIZE * 0.92)
GLYPH_DIAM = 410

FONT_CANDIDATES = [
    # macOS: Helvetica.ttc has Regular at index 0 and Bold at index 1
    ("/System/Library/Fonts/Helvetica.ttc", 1),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    # Linux / GitHub Actions
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ("DejaVuSans-Bold.ttf", 0),
]


def _interp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _get_font(size):
    for path, index in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except (IOError, OSError):
            continue
    raise RuntimeError(
        "Couldn't find a bold sans font. Edit FONT_CANDIDATES "
        "in scripts/gen_cover.py for your platform."
    )


def make_gradient():
    """3000x3000 vertical 3-stop gradient (Sunset)."""
    img = Image.new("RGB", (SIZE, SIZE))
    draw = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        if t <= 0.5:
            color = _interp(GRAD_TOP, GRAD_MID, t * 2)
        else:
            color = _interp(GRAD_MID, GRAD_BOT, (t - 0.5) * 2)
        draw.line([(0, y), (SIZE - 1, y)], fill=color)
    return img


def draw_play_glyph(img):
    draw = ImageDraw.Draw(img)
    x, y = PAD, PAD
    # Circle
    draw.ellipse([x, y, x + GLYPH_DIAM, y + GLYPH_DIAM], fill=INK)
    # Right-pointing triangle inside
    cx = x + GLYPH_DIAM // 2
    cy = y + GLYPH_DIAM // 2
    t_half_w = GLYPH_DIAM * 0.18
    t_half_h = GLYPH_DIAM * 0.21
    triangle = [
        (cx - t_half_w * 0.7, cy - t_half_h),
        (cx - t_half_w * 0.7, cy + t_half_h),
        (cx + t_half_w * 1.1, cy),
    ]
    draw.polygon(triangle, fill=CREAM)


def draw_wordmark(img):
    draw = ImageDraw.Draw(img)
    font = _get_font(FONT_SIZE)

    # "ME" anchored at bottom-left; "FEED" stacked above it.
    me_y = SIZE - PAD - FONT_SIZE
    feed_y = me_y - LINE_HEIGHT

    draw.text((PAD, feed_y), "FEED", fill=INK, font=font)
    draw.text((PAD, me_y), "ME", fill=INK, font=font)


def main():
    img = make_gradient()
    draw_play_glyph(img)
    draw_wordmark(img)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT, "JPEG", quality=90, optimize=True)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
