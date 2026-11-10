import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

MODULE = Path(__file__).resolve().parents[1]/"image_to_beads.py"
spec = importlib.util.spec_from_file_location("image_to_beads", MODULE)
beads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beads)


class BeadConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.palette = self.root/"palette.csv"
        self.palette.write_text('code,name,hex\nR,Red,#FF0000\nB,Blue,#0000FF\n', encoding="utf-8")

    def test_transparent_cells_counts_and_reconstructed_geometry(self):
        rgba = np.array([[[255,0,0,255],[0,0,255,255]],
                         [[0,255,0,0],[255,0,0,255]]], dtype=np.uint8)
        source = self.root/"input.png"
        Image.fromarray(rgba).save(source)
        data = beads.convert(source, self.palette, self.root/"out", 2)
        self.assertEqual(data["codes"], [["R", "B"], [None, "R"]])
        self.assertEqual(data["counts"], [2, 1])
        self.assertEqual(data["beadCount"] + data["blankCount"], 4)
        self.assertEqual((data["width"], data["height"]), (2, 2))
        with Image.open(self.root/"out/pixel-preview.png") as image:
            self.assertEqual(image.size, (24, 24))
            self.assertEqual(image.getpixel((2, 16))[3], 0)
        with (self.root/"out/color-counts.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(sum(int(r["quantity"]) for r in rows), 3)
        self.assertEqual(json.loads((self.root/"out/beads-grid.json").read_text(encoding="utf-8")), data)

    def test_transparent_rgb_does_not_pollute_boundary_color(self):
        source = self.root/"edge.png"
        Image.fromarray(np.array([[[255,0,0,255],[0,0,255,0]]], dtype=np.uint8)).save(source)
        sampled, active, coverage, _ = beads.sample_image(source, 1, 1, .4)
        np.testing.assert_allclose(sampled[0,0], [255,0,0])
        self.assertTrue(active[0,0])
        self.assertAlmostEqual(float(coverage[0,0]), .5)
        self.assertFalse(beads.sample_image(source,1,1,.6)[1][0,0])

    def test_aspect_ratio_and_explicit_height(self):
        source = self.root/"wide.png"
        Image.new("RGB", (12, 6), "red").save(source)
        self.assertEqual(beads.sample_image(source, 6)[0].shape, (3,6,3))
        self.assertEqual(beads.sample_image(source, 6, 5)[0].shape, (5,6,3))

    def test_duplicate_and_invalid_palette_are_rejected(self):
        for text in ('code,name,hex\nR,a,#FFFFFF\nR,b,#000000\n',
                     'code,name,hex\nR,a,black\n', 'number,color\n1,red\n'):
            self.palette.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                beads.read_palette(self.palette)

    def test_svg_escapes_user_labels(self):
        self.palette.write_text('code,name,hex\nR&,A < B,#FF0000\n', encoding="utf-8")
        source = self.root/"input.png"
        Image.new("RGB", (1,1), "red").save(source)
        beads.convert(source,self.palette,self.root/"out",1)
        document = ET.parse(self.root/"out/numbered-chart.svg")
        text = " ".join(document.getroot().itertext())
        self.assertIn("A < B", text)
        self.assertIn("R&", text)

    def test_lab_black_white_and_validation(self):
        lab = beads.srgb_to_lab(np.array([[0,0,0],[255,255,255]]))
        np.testing.assert_allclose(lab[:,0], [0,100], atol=1e-4)
        with self.assertRaises(ValueError):
            beads.sample_image(Path("missing.png"), 0)
        with self.assertRaises(ValueError):
            beads.sample_image(Path("missing.png"), 1, alpha_threshold=0)

    def test_csv_formula_like_palette_strings_are_literal_but_json_is_exact(self):
        self.palette.write_text('code,name,hex\n=1+1,@SUM(1),#FF0000\n', encoding="utf-8")
        source = self.root/"input.png"
        Image.new("RGB", (1,1), "red").save(source)
        data = beads.convert(source, self.palette, self.root/"out", 1)
        self.assertEqual(data["codes"], [["=1+1"]])
        self.assertEqual(data["palette"][0]["name"], "@SUM(1)")
        with (self.root/"out/color-counts.csv").open(encoding="utf-8-sig", newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["code"], "'=1+1")
        self.assertEqual(row["name"], "'@SUM(1)")
        self.assertEqual(row["quantity"], "1")
        document = ET.parse(self.root/"out/numbered-chart.svg")
        self.assertIn("=1+1", " ".join(document.getroot().itertext()))
        for prefix in ("=", "+", "-", "@"):
            self.assertTrue(beads.spreadsheet_text("  "+prefix+"value").startswith("'"))
        self.assertEqual(beads.spreadsheet_text("D01"), "D01")


if __name__ == "__main__":
    unittest.main()
