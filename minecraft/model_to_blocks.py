"""Turn a triangle mesh into colored Minecraft voxels and a Litematica schematic.

Geometry and scene transforms are evaluated, not replaced by a bounding box.
Run from the repository root: python minecraft/model_to_blocks.py --help
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
import time

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree
import trimesh


HERE = Path(__file__).resolve().parent


def load_parts(path: Path, up: str = "y") -> list[trimesh.Trimesh]:
    """Bake each scene-node transform separately, preserving its material/UVs."""
    loaded = trimesh.load(str(path), force="scene", process=False)
    parts = []
    for node in loaded.graph.nodes_geometry:
        transform, key = loaded.graph[node]
        geometry = loaded.geometry[key]
        if not isinstance(geometry, trimesh.Trimesh) or not len(geometry.faces):
            continue
        mesh = geometry.copy()
        mesh.apply_transform(transform)
        if up == "z":
            # Proper rotation: source (x,y,z) -> Minecraft (x,z,-y).
            mesh.apply_transform(np.array([[1, 0, 0, 0], [0, 0, 1, 0],
                                           [0, -1, 0, 0], [0, 0, 0, 1]]))
        if not np.isfinite(mesh.vertices).all():
            raise ValueError("Model contains non-finite vertices")
        parts.append(mesh)
    if not parts:
        raise ValueError("No triangle meshes were found")
    if len(parts) > 256 or sum(len(m.faces) for m in parts) > 2_000_000:
        raise ValueError("Simplify the input to <= 256 mesh nodes and <= 2 million triangles")
    return parts


def sample_colors(mesh: trimesh.Trimesh, count: int, seed: int):
    points, faces = trimesh.sample.sample_surface(mesh, count, seed=seed)
    weights = trimesh.triangles.points_to_barycentric(mesh.triangles[faces], points)
    vis = mesh.visual
    if vis.kind == "texture" and vis.uv is not None:
        uv = np.einsum("ni,nij->nj", weights, vis.uv[mesh.faces[faces]])
        material = vis.material
        image = getattr(material, "baseColorTexture", None)
        if image is None:
            image = getattr(material, "image", None)
        factor = getattr(material, "baseColorFactor", None)
        if image is not None:
            colors = trimesh.visual.color.uv_to_color(uv, image).astype(float)
            if factor is not None:
                factor = np.asarray(factor, dtype=float)
                if factor.max() > 1:
                    factor /= 255.0
                colors *= factor
        else:
            color = factor if factor is not None else getattr(material, "diffuse", [180, 180, 180, 255])
            color = np.asarray(color, dtype=float)
            if color.max() <= 1:
                color *= 255.0
            colors = np.tile(color, (count, 1))
    elif vis.kind == "vertex":
        colors = np.einsum("ni,nij->nj", weights, vis.vertex_colors[mesh.faces[faces]])
    else:
        colors = vis.face_colors[faces]
    return points, np.asarray(colors[:, :3]).clip(0, 255)


def read_palette(path: Path):
    palette = json.loads(path.read_text(encoding="utf-8"))
    blocks = palette["blocks"]
    if not blocks or len(blocks) > 256:
        raise ValueError("Block palette needs 1..256 entries")
    for entry in blocks:
        if not entry["block"].startswith("minecraft:") or not entry["block"].replace("minecraft:", "", 1).replace("_", "").isalnum():
            raise ValueError("Only plain minecraft:block_name identifiers are supported")
        if entry["block"] in {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}:
            raise ValueError("Air is reserved for unoccupied cells, not a color swatch")
        rgb = entry["rgb"]
        if len(rgb) != 3 or any(not isinstance(c, int) or not 0 <= c <= 255 for c in rgb):
            raise ValueError("Each palette RGB must contain three integers in [0,255]")
    if len({b["block"] for b in blocks}) != len(blocks):
        raise ValueError("Duplicate block identifiers in palette")
    return palette


def srgb_to_linear(rgb):
    v = np.asarray(rgb, dtype=float) / 255.0
    return np.where(v <= .04045, v / 12.92, ((v + .055) / 1.055) ** 2.4)


def voxelize(parts, palette, max_axis=48, solid=False, seed=42):
    if not 4 <= max_axis <= 160:
        raise ValueError("max_axis must be between 4 and 160")
    if solid and any(not m.is_watertight for m in parts):
        raise ValueError("--solid requires every mesh node to be watertight; repair it or use surface mode")
    bounds = np.array([m.bounds for m in parts])
    low, high = bounds[:, 0].min(axis=0), bounds[:, 1].max(axis=0)
    longest = float((high - low).max())
    if longest <= 0:
        raise ValueError("Model has zero extent")
    scale = (max_axis - 1) / longest
    transformed = []
    for original in parts:
        mesh = original.copy()
        mesh.apply_translation(-low)
        mesh.apply_scale(scale)
        transformed.append(mesh)
    occupied = set()
    sample_points, sample_rgb = [], []
    total_area = sum(m.area for m in transformed)
    if total_area <= 0 or not np.isfinite(total_area):
        raise ValueError("Model has no finite nonzero triangle area")
    for index, mesh in enumerate(transformed):
        grid = mesh.voxelized(pitch=1.0, method="subdivide")
        if solid:
            grid = grid.fill()
        occupied.update(map(tuple, np.rint(grid.points).astype(int).tolist()))
        if len(occupied) > 2_000_000:
            raise ValueError("More than two million blocks; lower --max-axis")
        count = max(256, int(150_000 * mesh.area / total_area))
        points, colors = sample_colors(mesh, count, seed + index)
        sample_points.append(points)
        sample_rgb.append(colors)
    coords = np.asarray(sorted(occupied, key=lambda p: (p[1], p[2], p[0])), dtype=int)
    if not len(coords):
        raise ValueError("Voxelization produced no blocks")
    nearest = cKDTree(np.concatenate(sample_points)).query(coords, workers=1)[1]
    rgb = np.concatenate(sample_rgb)[nearest]
    target = np.array([entry["rgb"] for entry in palette["blocks"]])
    target_linear = srgb_to_linear(target)
    # Bounded chunks avoid an occupied-voxel x palette x channel memory spike.
    indices = np.concatenate([
        ((srgb_to_linear(chunk)[:, None] - target_linear[None]) ** 2).sum(axis=2).argmin(axis=1)
        for chunk in np.array_split(rgb, max(1, math.ceil(len(rgb) / 20_000)))
    ])
    origin = coords.min(axis=0)
    coords -= origin
    size = coords.max(axis=0) + 1
    return {
        "schema_version": 1, "axes": "Minecraft: +X right, +Y up, +Z forward",
        "mode": "solid" if solid else "surface",
        "size": size.tolist(), "block_count": len(coords),
        "input_origin_after_axis_rotation": low.tolist(),
        "input_units_per_block": 1 / scale,
        "sample_seed": seed, "color_method": "nearest deterministic UV/vertex surface sample; linear-RGB palette distance",
        "palette": palette["blocks"],
        "blocks": [[int(x), int(y), int(z), int(p)] for (x, y, z), p in zip(coords, indices)],
    }


# Minimal big-endian NBT writer. Palette bit fields follow Litematica's continuous
# bit-array layout (a state may cross a 64-bit boundary), not modern chunk storage.
def _string(value):
    data = value.encode("utf-8")
    if len(data) > 65535:
        raise ValueError("NBT string is too long")
    return struct.pack(">H", len(data)) + data


def _payload(kind, value):
    if kind == 3:
        return struct.pack(">i", value)
    if kind == 4:
        return struct.pack(">q", value)
    if kind == 8:
        return _string(value)
    if kind == 9:
        item_kind, items = value
        return bytes([item_kind]) + struct.pack(">i", len(items)) + b"".join(_payload(item_kind, item) for item in items)
    if kind == 10:
        return b"".join(bytes([child_kind]) + _string(name) + _payload(child_kind, child)
                        for name, (child_kind, child) in value.items()) + b"\0"
    if kind == 12:
        return struct.pack(">i", len(value)) + b"".join(struct.pack(">q", v) for v in value)
    raise ValueError(f"Unsupported NBT tag {kind}")


def pack_states(states, palette_count):
    bits = max(2, (palette_count - 1).bit_length())
    longs = [0] * math.ceil(len(states) * bits / 64)
    for index, value in enumerate(states):
        start = index * bits
        word, shift = divmod(start, 64)
        longs[word] |= (int(value) << shift) & ((1 << 64) - 1)
        if shift + bits > 64:
            longs[word + 1] |= int(value) >> (64 - shift)
    return [n - (1 << 64) if n >= (1 << 63) else n for n in longs]


def write_litematic(data, path: Path, name="beads_philosophy"):
    sx, sy, sz = data["size"]
    palette = [{"Name": (8, "minecraft:air")}] + [
        {"Name": (8, entry["block"])} for entry in data["palette"]
    ]
    states = np.zeros(sx * sy * sz, dtype=np.int32)
    for x, y, z, color_index in data["blocks"]:
        states[(y * sz + z) * sx + x] = color_index + 1
    vector = lambda x, y, z: {"x": (3, x), "y": (3, y), "z": (3, z)}
    stamp = int(time.time() * 1000)
    root = {
        "Version": (3, 6), "SubVersion": (3, 1), "MinecraftDataVersion": (3, 3955),
        "Metadata": (10, {
            "Name": (8, name), "Author": (8, "beads_philosophy"),
            "Description": (8, "Mesh-derived educational voxel build; Minecraft Java 1.21.1"),
            "RegionCount": (3, 1), "TimeCreated": (4, stamp), "TimeModified": (4, stamp),
            "TotalBlocks": (3, data["block_count"]), "TotalVolume": (3, sx * sy * sz),
            "EnclosingSize": (10, vector(sx, sy, sz)),
        }),
        "Regions": (10, {"build": (10, {
            "Position": (10, vector(0, 0, 0)), "Size": (10, vector(sx, sy, sz)),
            "BlockStatePalette": (9, (10, palette)),
            "BlockStates": (12, pack_states(states, len(palette))),
            "Entities": (9, (10, [])), "TileEntities": (9, (10, [])),
            "PendingBlockTicks": (9, (10, [])), "PendingFluidTicks": (9, (10, [])),
        })}),
    }
    path.write_bytes(gzip.compress(b"\x0a" + _string("") + _payload(10, root), mtime=0))


def save_outputs(data, out: Path, name="beads_philosophy"):
    out.mkdir(parents=True, exist_ok=True)
    (out / "blocks.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_litematic(data, out / "build.litematic", name)
    with (out / "build-order.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["step", "x", "y_layer", "z", "minecraft_block"])
        writer.writerows((i + 1, x, y, z, data["palette"][p]["block"])
                        for i, (x, y, z, p) in enumerate(data["blocks"]))
    counts = np.bincount([p for *_, p in data["blocks"]], minlength=len(data["palette"]))
    with (out / "materials.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["minecraft_block", "count", "full_stacks", "remainder"])
        writer.writerows((entry["block"], int(n), int(n // 64), int(n % 64))
                        for entry, n in zip(data["palette"], counts) if n)
    sx, sy, sz = data["size"]
    # Orthographic front projection looking along +Z; closest voxel wins.
    pixels = np.zeros((sy, sx, 4), dtype=np.uint8)
    for x, y, z, p in sorted(data["blocks"], key=lambda row: -row[2]):
        pixels[sy - 1 - y, x] = [*data["palette"][p]["rgb"], 255]
    preview = Image.fromarray(pixels)
    factor = max(1, min(16, 1024 // max(sx, sy)))
    preview.resize((sx * factor, sy * factor), Image.Resampling.NEAREST).save(out / "front.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="GLB, GLTF, OBJ or STL mesh")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-axis", type=int, default=48, help="Approximate longest dimension in blocks (4..160)")
    parser.add_argument("--up", choices=["y", "z"], default="y", help="Input up-axis; GLB normally y, STL normally z")
    parser.add_argument("--solid", action="store_true", help="Fill watertight mesh interiors; default exports surface voxels")
    parser.add_argument("--palette", type=Path, default=HERE / "palettes" / "concrete.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        data = voxelize(load_parts(args.input, args.up), read_palette(args.palette), args.max_axis, args.solid, args.seed)
        data["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
        data["input_up"] = args.up
        save_outputs(data, args.out, args.input.stem)
    except (ValueError, OSError) as error:
        parser.exit(2, f"Error: {error}\n")
    print(json.dumps({"out": str(args.out), "blocks": data["block_count"], "size": data["size"], "mode": data["mode"]}))


if __name__ == "__main__":
    main()
