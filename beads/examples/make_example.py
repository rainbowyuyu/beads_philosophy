"""Create an original, freely redistributable geometric flower sample."""
from pathlib import Path
from PIL import Image, ImageDraw

path = Path(__file__).resolve().parent / "flower.png"
image = Image.new("RGBA", (384, 384), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((179, 177, 204, 337), radius=9, fill="#3A7E83")
draw.ellipse((104, 244, 188, 282), fill="#659A7C")
draw.ellipse((197, 223, 282, 261), fill="#659A7C")
for bounds in [(141, 40, 242, 158), (75, 100, 183, 213),
               (201, 100, 309, 213), (141, 162, 242, 274)]:
    draw.ellipse(bounds, fill="#E9849C")
draw.ellipse((147, 112, 236, 201), fill="#E7AE49")
draw.ellipse((165, 140, 172, 147), fill="#292E47")
draw.ellipse((209, 140, 216, 147), fill="#292E47")
draw.arc((174, 145, 207, 178), 0, 180, fill="#292E47", width=4)
image.save(path)
print(path)
