"""Draw the Habits home-screen icon: a white check on violet. Run once."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
for size in (192, 512):
    im = Image.new("RGBA", (size, size), "#a78bfa")
    d = ImageDraw.Draw(im)
    r = size * 0.22
    d.rounded_rectangle([0, 0, size, size], radius=r, fill="#a78bfa")
    w = max(6, size // 12)
    pts = [(size * 0.26, size * 0.52), (size * 0.44, size * 0.70), (size * 0.76, size * 0.34)]
    d.line(pts, fill="white", width=w, joint="curve")
    im.save(ROOT / f"habits-icon-{size}.png")
    print("wrote", size)
