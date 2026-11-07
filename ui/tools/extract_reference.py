"""Build-time extraction of artwork ONLY from the user-approved reference.

No runtime Pillow dependency. Controls, words, timestamps, and demo records are
never extracted. Pass the original PNG as the sole command-line argument.
"""
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFilter


def extract(source: Path, output: Path):
    original = Image.open(source).convert("RGB")
    if original.size != (1536, 1024):
        raise ValueError("The approved reference must be the original 1536x1024 image")
    output.mkdir(parents=True, exist_ok=True)
    # Ten-point outline of the actual faceted crystal, not a font glyph.
    polygon = [(207, 438), (314, 537), (423, 438), (423, 578), (381, 617),
               (381, 540), (314, 602), (247, 540), (247, 617), (207, 578)]
    mask = Image.new("L", original.size)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    crystal = original.convert("RGBA")
    crystal.putalpha(mask.filter(ImageFilter.GaussianBlur(.35)))
    crystal.crop((198, 429, 433, 627)).save(output / "crystal.png")

    region = (33, 216, 567, 797)
    image = original.crop(region).convert("RGBA")
    erase = mask.filter(ImageFilter.MaxFilter(19)).filter(ImageFilter.GaussianBlur(5)).crop(region)
    pixels, removal = image.load(), erase.load()
    background = (7, 22, 43)
    for y in range(image.height):
        for x in range(image.width):
            rgb = pixels[x, y][:3]
            differences = [max(0, rgb[i] - background[i]) for i in range(3)]
            opacity = max(differences[i] / (255 - background[i]) for i in range(3))
            # No hard crop seam. Lower luminosity carries no opaque navy block.
            edge = min(1.0, x / 14, (image.width - x - 1) / 14,
                       y / 24, (image.height - y - 1) / 28)
            alpha = opacity * edge * (1 - removal[x, y] / 255)
            if opacity < .045:
                pixels[x, y] = (0, 0, 0, 0)
            else:
                color = tuple(min(255, round(background[i] + differences[i] / opacity)) for i in range(3))
                pixels[x, y] = (*color, round(255 * alpha))
    image.save(output / "ribbons.png")
    # All additional vector assets are original, tiny, local, and dependency-free.
    (output / "send.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path fill="#e9fbff" d="M4 14 28 4 21 29 15 20 4 14zm13 3 3 7 4-15-14 6 6 2 8-8-7 8z"/></svg>''', encoding="utf-8")


if __name__ == "__main__":
    extract(Path(sys.argv[1]), Path(__file__).resolve().parents[1] / "assets")
