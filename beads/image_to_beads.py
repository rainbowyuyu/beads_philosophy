"""Convert a local image to a numbered bead pattern using a user-supplied palette.

Only numpy and Pillow are required. DEMO codes are not manufacturer bead codes.
"""
from __future__ import annotations

import argparse
import csv
from functools import lru_cache
import hashlib
import html
import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent


def read_palette(path: Path) -> list[dict]:
    """Read code,name,hex CSV; preserve exact user codes, rejecting ambiguity."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"code", "name", "hex"}.issubset(reader.fieldnames or []):
            raise ValueError("Palette CSV must contain code,name,hex columns")
        palette, seen = [], set()
        for line, row in enumerate(reader, start=2):
            code, name, color = (str(row.get(key) or "").strip() for key in ("code", "name", "hex"))
            if not code or len(code) > 24 or any(ord(c) < 32 for c in code):
                raise ValueError(f"Invalid palette code on CSV line {line}")
            if code in seen:
                raise ValueError(f"Duplicate palette code: {code}")
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                raise ValueError(f"Invalid #RRGGBB value on CSV line {line}")
            if len(name) > 100 or any(ord(c) < 32 for c in name):
                raise ValueError(f"Invalid palette name on CSV line {line}")
            seen.add(code)
            palette.append({"code": code, "name": name or code, "hex": color.upper()})
    if not 1 <= len(palette) <= 256:
        raise ValueError("Palette must contain 1 to 256 colors")
    return palette


def sample_image(path: Path, width: int, height: int | None = None, alpha_threshold: float = 0.35):
    """Area-average premultiplied sRGB; ignore hidden RGB in transparent pixels."""
    if not 1 <= width <= 256 or (height is not None and not 1 <= height <= 256):
        raise ValueError("Grid width and height must each be between 1 and 256")
    if not math.isfinite(alpha_threshold) or not 0 < alpha_threshold <= 1:
        raise ValueError("Alpha threshold must be greater than 0 and at most 1")
    with Image.open(path) as loaded:
        if loaded.width * loaded.height > 40_000_000:
            raise ValueError("Source image exceeds the 40-megapixel working limit")
        src = ImageOps.exif_transpose(loaded).convert("RGBA")
        source_size = src.size
        if height is None:
            height = max(1, round(width * src.height / src.width))
            if height > 256:
                raise ValueError("Automatic grid height exceeds 256; reduce --width or set --height")
        rgba = np.asarray(src, dtype=np.float32)
    alpha = rgba[..., 3] / 255.0
    def area(data):
        return np.asarray(Image.fromarray(data.astype(np.float32)).resize((width, height), Image.Resampling.BOX))
    coverage = area(alpha)
    sampled = np.stack([area(rgba[..., c] * alpha) for c in range(3)], axis=-1)
    sampled /= np.maximum(coverage[..., None], 1e-8)
    sampled = np.clip(sampled, 0, 255)
    return sampled, coverage >= alpha_threshold, coverage, source_size


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0..255) -> CIELAB, D65/2 degree. No external color library."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.array([[0.4124564, 0.3575761, 0.1804375],
                             [0.2126729, 0.7151522, 0.0721750],
                             [0.0193339, 0.1191920, 0.9503041]]).T
    xyz /= np.array([0.95047, 1.0, 1.08883])
    delta = 6 / 29
    f = np.where(xyz > delta ** 3, np.cbrt(xyz), xyz / (3 * delta ** 2) + 4 / 29)
    return np.stack([116*f[..., 1]-16, 500*(f[..., 0]-f[..., 1]), 200*(f[..., 1]-f[..., 2])], axis=-1)


def quantize(sampled: np.ndarray, active: np.ndarray, palette: list[dict]) -> np.ndarray:
    colors = np.array([[int(p["hex"][i:i+2], 16) for i in (1, 3, 5)] for p in palette])
    targets = srgb_to_lab(colors)
    indices = np.full(active.shape, -1, dtype=np.int32)
    valid = srgb_to_lab(sampled[active])
    closest = np.empty(len(valid), dtype=np.int32)
    for start in range(0, len(valid), 2048):
        batch = valid[start:start+2048]
        distance = np.sum((batch[:, None, :] - targets[None, :, :]) ** 2, axis=-1)
        closest[start:start+2048] = np.argmin(distance, axis=1)
    indices[active] = closest
    return indices


@lru_cache(maxsize=64)
def find_font(size: int, supplied: Path | None = None):
    if supplied:
        return ImageFont.truetype(str(supplied), size)
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                      "/System/Library/Fonts/PingFang.ttc"):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


def spreadsheet_text(value: str) -> str:
    """Keep imported palette strings literal when a spreadsheet opens the CSV.

    The apostrophe is a spreadsheet text prefix; exact values remain in JSON/SVG.
    Checking after whitespace also covers spreadsheet applications which trim it.
    """
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def make_chart(indices, palette, counts, destination: Path, font: Path | None = None):
    rows, cols = indices.shape
    cell, margin = 32, 46
    used = [i for i, n in enumerate(counts) if n]
    canvas_width = max(850, cols * cell + margin * 2)
    legend_columns = min(3, max(1, canvas_width // 280))
    legend_width = (canvas_width - 2*margin) / legend_columns
    legend_rows = max(1, math.ceil(len(used)/legend_columns))
    canvas_height = rows*cell + margin*2 + 76 + legend_rows*38
    if canvas_width * canvas_height > 75_000_000:
        raise ValueError("Chart raster is too large; reduce grid dimensions or palette size")
    chart = Image.new("RGB", (canvas_width, canvas_height), "#F9F6EF")
    draw = ImageDraw.Draw(chart)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">',
           '<rect width="100%" height="100%" fill="#F9F6EF"/>']
    def text(x, y, value, size=12, color="#34373B", anchor="middle"):
        escaped = html.escape(str(value))
        svg.append(f'<text x="{x}" y="{y}" font-family="sans-serif" font-size="{size}" fill="{color}" text-anchor="{anchor}" dominant-baseline="central">{escaped}</text>')
        draw.text((x, y), str(value), font=find_font(size, font), fill=color, anchor="mm" if anchor == "middle" else "lm")
    text(margin, 20, f"BEAD PATTERN  |  {cols} x {rows}  |  {int(sum(counts))} beads", 20, anchor="start")
    for row in range(rows):
        for col in range(cols):
            index = int(indices[row, col])
            x, y = margin + col*cell, margin + row*cell
            fill = palette[index]["hex"] if index >= 0 else "#EEEAE2"
            draw.rectangle((x, y, x+cell, y+cell), fill=fill, outline="#BBB8B1")
            svg.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="{fill}" stroke="#BBB8B1" stroke-width="0.5"/>')
            if index < 0:
                # A blank cell means no bead, not a transparent/white color code.
                continue
            rgb = [int(fill[i:i+2], 16) for i in (1, 3, 5)]
            ink = "#FFFDF8" if np.dot(rgb, [0.2126, 0.7152, 0.0722]) < 130 else "#25272B"
            code = palette[index]["code"]
            size = max(1, min(12, int(45 / max(1, len(code)))))
            text(x+cell/2, y+cell/2, code, size, ink)
    for col in range(cols):
        if cols <= 60 or (col+1) % 5 == 0:
            text(margin+(col+0.5)*cell, margin-12, col+1, 10)
    for row in range(rows):
        if rows <= 60 or (row+1) % 5 == 0:
            text(margin-17, margin+(row+0.5)*cell, row+1, 10)
    legend_y = margin+rows*cell+35
    text(margin, legend_y, "COLOR CODE / NAME / QUANTITY   |   Blank cell = no bead", 14, anchor="start")
    for pos, index in enumerate(used):
        x = margin + (pos % legend_columns)*legend_width
        y = legend_y+35+(pos//legend_columns)*38
        p = palette[index]
        draw.ellipse((x, y-9, x+18, y+9), fill=p["hex"], outline="#888888")
        svg.append(f'<circle cx="{x+9}" cy="{y}" r="9" fill="{p["hex"]}" stroke="#888888"/>')
        label = f'{p["code"]} / {p["name"]} / {counts[index]}'
        # Fit the full legend string; JSON and CSV always preserve exact names.
        size = 12
        while size > 6 and draw.textlength(label, font=find_font(size, font)) > legend_width-35:
            size -= 1
        text(x+28, y, label, size, anchor="start")
    svg.append("</svg>")
    chart.save(destination/"numbered-chart.png")
    (destination/"numbered-chart.svg").write_text("\n".join(svg), encoding="utf-8")


def convert(input_path: Path, palette_path: Path, output: Path, width: int = 32,
            height: int | None = None, alpha_threshold: float = .35, font: Path | None = None):
    palette = read_palette(palette_path)
    sampled, active, coverage, source_size = sample_image(input_path, width, height, alpha_threshold)
    indices = quantize(sampled, active, palette)
    counts = np.bincount(indices[active], minlength=len(palette)).astype(int).tolist()
    grid_height, grid_width = indices.shape
    output.mkdir(parents=True, exist_ok=True)
    data = {
        "schemaVersion": 1, "width": grid_width, "height": grid_height,
        "origin": "top-left; rows[y][x]; null means no bead", "palette": palette,
        "indices": [[None if i < 0 else int(i) for i in row] for row in indices],
        "codes": [[None if i < 0 else palette[i]["code"] for i in row] for row in indices],
        "counts": counts, "beadCount": int(active.sum()), "blankCount": int((~active).sum()),
        "sampling": "Pillow BOX area resampling of alpha-premultiplied sRGB; no dithering",
        "colorMatching": "nearest CIELAB D65 color, squared Delta E 1976; not physical color calibration",
        "alphaThreshold": alpha_threshold,
        "source": {"file": input_path.name, "size": list(source_size), "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()},
        "paletteSource": {"file": palette_path.name, "sha256": hashlib.sha256(palette_path.read_bytes()).hexdigest()},
    }
    (output/"beads-grid.json").write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    with (output/"color-counts.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["code", "name", "hex", "quantity"])
        for p, n in zip(palette, counts):
            if n:
                writer.writerow([spreadsheet_text(p["code"]), spreadsheet_text(p["name"]), p["hex"], n])
    pixels = np.zeros((*indices.shape, 4), dtype=np.uint8)
    colors = np.array([[int(p["hex"][i:i+2], 16) for i in (1, 3, 5)] for p in palette], dtype=np.uint8)
    pixels[active, :3] = colors[indices[active]]
    pixels[active, 3] = 255
    Image.fromarray(pixels).resize((grid_width*12, grid_height*12), Image.Resampling.NEAREST).save(output/"pixel-preview.png")
    make_chart(indices, palette, counts, output, font)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local PNG/JPEG image")
    parser.add_argument("--palette", type=Path, default=HERE/"palettes/demo.csv", help="CSV with code,name,hex columns")
    parser.add_argument("--width", type=int, default=32, help="Grid columns, 1..256")
    parser.add_argument("--height", type=int, help="Grid rows; default preserves source aspect ratio")
    parser.add_argument("--alpha-threshold", type=float, default=.35, help="Minimum cell alpha coverage (0,1]")
    parser.add_argument("--font", type=Path, help="Optional local TTF/TTC font for raster labels")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = convert(args.input, args.palette, args.output, args.width, args.height, args.alpha_threshold, args.font)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"output": str(args.output), "grid": [data["width"], data["height"]],
                      "beads": data["beadCount"], "colors": sum(c > 0 for c in data["counts"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
