"""Create a small original T-shaped calibration object; no external assets."""
from pathlib import Path
import sys

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import triangulate


def make_t_shape():
    # Outline in X/Z. Extrusion in Y gives two long 16 mm horizontal overhangs.
    outline = [(-4, 0), (4, 0), (4, 20), (20, 20), (20, 26), (-20, 26), (-20, 20), (-4, 20)]
    polygon = Polygon(outline)
    lookup = {p: i for i, p in enumerate(outline)}
    count = len(outline)
    vertices = [[x, y, z] for y in (-5, 5) for x, z in outline]
    faces = []
    for triangle in triangulate(polygon):
        if not polygon.covers(triangle):
            continue
        ids = [lookup[(float(x), float(z))] for x, z in list(triangle.exterior.coords)[:3]]
        faces.append(ids)
        faces.append([j + count for j in reversed(ids)])
    for i in range(count):
        j = (i + 1) % count
        faces.extend([[i, j, j + count], [i, j + count, i + count]])
    mesh = trimesh.Trimesh(vertices=np.array(vertices), faces=np.array(faces), process=True)
    mesh.fix_normals()
    assert mesh.is_watertight and mesh.volume > 0
    return mesh


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "t-overhang.stl"
    output.parent.mkdir(parents=True, exist_ok=True)
    make_t_shape().export(output)
    print(output)
