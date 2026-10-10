"""Draw packaging/spory.ico: an amber battery on a graphite tile."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
TILE = (19, 18, 15, 255)  # theme INK_BG
INK = (238, 231, 215, 255)
AMBER = (243, 168, 59, 255)


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=52, fill=TILE)
    body = (44, 82, 196, 174)
    d.rounded_rectangle(body, radius=20, outline=INK, width=14)
    d.rounded_rectangle((200, 108, 220, 148), radius=6, fill=INK)
    d.rounded_rectangle((66, 104, 66 + int((174 - 66) * 0.7), 152), radius=8, fill=AMBER)
    return image


def main() -> Path:
    target = Path(__file__).with_name("spory.ico")
    draw().save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return target


if __name__ == "__main__":
    print(main())
