import gzip
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image
import trimesh

MODULE_PATH = Path(__file__).resolve().parents[1] / "model_to_blocks.py"
spec = importlib.util.spec_from_file_location("model_to_blocks", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def read_nbt(data):
    """Small independent binary reader for the tags used by a schematic."""
    stream = io.BytesIO(data)
    read = lambda code: struct.unpack(code, stream.read(struct.calcsize(code)))[0]
    string = lambda: stream.read(read(">H")).decode("utf-8")

    def payload(kind):
        if kind == 3:
            return read(">i")
        if kind == 4:
            return read(">q")
        if kind == 8:
            return string()
        if kind == 9:
            child, count = read(">B"), read(">i")
            return [payload(child) for _ in range(count)]
        if kind == 10:
            result = {}
            while kind := read(">B"):
                name = string()
                result[name] = payload(kind)
            return result
        if kind == 12:
            return [read(">q") for _ in range(read(">i"))]
        raise AssertionError(f"Unexpected tag {kind}")

    assert read(">B") == 10
    assert string() == ""
    result = payload(10)
    assert stream.read() == b""
    return result


class MinecraftTests(unittest.TestCase):
    def setUp(self):
        self.palette = module.read_palette(MODULE_PATH.parent / "palettes/concrete.json")

    def test_scene_nodes_keep_transforms(self):
        cube = trimesh.creation.box(extents=[1, 1, 1])
        scene = trimesh.Scene()
        scene.add_geometry(cube, transform=trimesh.transformations.translation_matrix([8, 3, 1]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offset.glb"
            scene.export(path)
            parts = module.load_parts(path)
        np.testing.assert_allclose(parts[0].centroid, [8, 3, 1], atol=1e-6)

    def test_surface_has_empty_interior_and_solid_does_not(self):
        cube = trimesh.creation.box(extents=[2, 2, 2])
        shell = module.voxelize([cube], self.palette, max_axis=7)
        solid = module.voxelize([cube], self.palette, max_axis=7, solid=True)
        center = (3, 3, 3)
        self.assertNotIn(center, {tuple(row[:3]) for row in shell["blocks"]})
        self.assertIn(center, {tuple(row[:3]) for row in solid["blocks"]})
        self.assertGreater(solid["block_count"], shell["block_count"])
        self.assertEqual(solid["block_count"], 7 ** 3)

    def test_open_mesh_cannot_claim_solid(self):
        cube = trimesh.creation.box()
        cube.update_faces(np.arange(len(cube.faces) - 1))
        with self.assertRaisesRegex(ValueError, "watertight"):
            module.voxelize([cube], self.palette, max_axis=7, solid=True)

    def test_pbr_texture_and_factor_are_sampled(self):
        mesh = trimesh.creation.box()
        texture = Image.new("RGBA", (2, 2), (240, 100, 60, 255))
        material = trimesh.visual.material.PBRMaterial(baseColorTexture=texture, baseColorFactor=[.5, 1, 1, 1])
        mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(mesh.vertices), 2)), material=material)
        _, rgb = module.sample_colors(mesh, 20, 123)
        np.testing.assert_allclose(rgb[:, 0], 240 * 128 / 255, atol=1)
        np.testing.assert_allclose(rgb[:, 1], 100, atol=1)

    def test_litematic_palette_coordinates_and_cross_word_bits(self):
        blocks = [[x, y, z, (x + 3*y + 7*z) % 16]
                  for y in range(4) for z in range(5) for x in range(7) if (x + y + z) % 3]
        data = {"size": [7, 4, 5], "palette": self.palette["blocks"],
                "blocks": blocks, "block_count": len(blocks)}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.litematic"
            module.write_litematic(data, path)
            root = read_nbt(gzip.decompress(path.read_bytes()))
        self.assertEqual(root["MinecraftDataVersion"], 3955)
        self.assertEqual(root["Metadata"]["TotalBlocks"], len(blocks))
        region = root["Regions"]["build"]
        self.assertEqual(region["BlockStatePalette"][0]["Name"], "minecraft:air")
        self.assertEqual(region["Size"], {"x": 7, "y": 4, "z": 5})
        # Reconstruct the whole unsigned integer stream independently, then decode.
        aggregate = sum((word & ((1 << 64) - 1)) << (64 * i)
                        for i, word in enumerate(region["BlockStates"]))
        bits = max(2, (len(region["BlockStatePalette"]) - 1).bit_length())
        expected = {(x, y, z): p + 1 for x, y, z, p in blocks}
        for y in range(4):
            for z in range(5):
                for x in range(7):
                    offset = (y * 5 * 7 + z * 7 + x) * bits
                    self.assertEqual((aggregate >> offset) & ((1 << bits) - 1), expected.get((x, y, z), 0))


if __name__ == "__main__":
    unittest.main()
