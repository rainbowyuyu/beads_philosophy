import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import trimesh
from shapely.geometry import LineString

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE))
from slice_and_support import export_preview, load_model, make_slices, make_supports, section_geometry

spec = importlib.util.spec_from_file_location("demo", MODULE / "examples" / "make_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class GeometryTests(unittest.TestCase):
    def cube(self):
        mesh = trimesh.creation.box(extents=[20, 10, 10])
        mesh.apply_translation([0, 0, 5])
        return mesh

    def test_cube_exact_sections_and_path_containment(self):
        mesh = self.cube()
        layers = make_slices(mesh, layer_height=3, line_width=0.8, infill_spacing=3)
        self.assertEqual(len(layers), 4)
        self.assertEqual([l["height_mm"] for l in layers], [3, 3, 3, 1])
        self.assertEqual([l["slice_z_mm"] for l in layers], [1.5, 4.5, 7.5, 9.5])
        for layer in layers:
            self.assertAlmostEqual(layer["section_area_mm2"], 200, places=5)
            material = section_geometry(mesh, layer["slice_z_mm"])
            self.assertGreater(len(layer["paths"]), 1)
            for path in layer["paths"]:
                self.assertTrue(material.covers(LineString(path["points"])))

    def test_cube_needs_no_bed_support(self):
        supports, rejected, geometry = make_supports(self.cube())
        self.assertEqual(supports, [])
        self.assertIsNone(geometry)

    def test_t_underhang_gets_columns_away_from_stem(self):
        mesh = demo.make_t_shape()
        self.assertAlmostEqual(section_geometry(mesh, 10).area, 80)
        self.assertAlmostEqual(section_geometry(mesh, 23).area, 400)
        supports, rejected, geometry = make_supports(mesh, spacing=4, radius=.6, gap=.25)
        self.assertGreater(len(supports), 0)
        self.assertTrue(geometry.is_watertight)
        for support in supports:
            self.assertGreater(abs(support["xy_mm"][0]), 4)
            self.assertAlmostEqual(support["top_z_mm"], 19.75)
            self.assertAlmostEqual(support["contact_z_mm"], 20)

    def test_model_below_contact_is_rejected(self):
        base = trimesh.creation.box(extents=[10, 10, 5])
        base.apply_translation([0, 0, 2.5])
        plate = trimesh.creation.box(extents=[18, 18, 2])
        plate.apply_translation([0, 0, 21])
        mesh = trimesh.util.concatenate([base, plate])
        supports, rejected, geometry = make_supports(mesh, spacing=4)
        self.assertTrue(any(c["xy_mm"] == [0, 0] and c["reason"] == "model_below_contact" for c in rejected))
        self.assertFalse(any(c["xy_mm"] == [0, 0] for c in supports))

    def test_scene_transform_and_glb_y_up(self):
        # A transformed GLB scene has a 0.02 m Y extent = 20 mm after Y->Z.
        model = trimesh.creation.box(extents=[.01, .02, .03])
        transform = np.eye(4)
        transform[:3, 3] = [1, 2, 3]
        scene = trimesh.Scene()
        scene.add_geometry(model, transform=transform)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.glb"
            scene.export(path)
            loaded = load_model(path, "m", "y")
            self.assertTrue(np.allclose(loaded.extents, [10, 30, 20], atol=.001))
            self.assertAlmostEqual(loaded.bounds[0, 2], 0)

    def test_hollow_section_keeps_hole(self):
        mesh = trimesh.creation.annulus(r_min=5, r_max=10, height=10, sections=64)
        mesh.apply_translation([0, 0, 5])
        section = section_geometry(mesh, 5)
        from shapely.geometry import Point
        self.assertFalse(section.contains(Point(0, 0)))
        self.assertTrue(section.contains(Point(7, 0)))
        for layer in make_slices(mesh, layer_height=2):
            for path in layer["paths"]:
                self.assertTrue(section.buffer(1e-5).covers(LineString(path["points"])))

    def test_reject_invalid_parameters(self):
        with self.assertRaises(ValueError):
            make_supports(self.cube(), spacing=.5, radius=1)
        with self.assertRaises(ValueError):
            make_slices(self.cube(), layer_height=0)


if __name__ == "__main__":
    unittest.main()
