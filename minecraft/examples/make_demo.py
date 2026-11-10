"""Create an original low-poly sprout sculpture; no third-party character assets."""
from pathlib import Path
import argparse
import trimesh


def make_demo(path):
    scene = trimesh.Scene()
    pot = trimesh.creation.revolve([[0, -.85], [.85, -.85], [1.25, .85], [0, .85]], sections=20)
    pot.apply_transform(trimesh.transformations.rotation_matrix(-1.5707963267948966, [1, 0, 0]))
    pot.visual.vertex_colors = [214, 101, 143, 255]
    scene.add_geometry(pot, node_name="pot")
    stem = trimesh.creation.box(extents=[.25, 2.1, .25])
    stem.visual.vertex_colors = [94, 168, 24, 255]
    transform = trimesh.transformations.translation_matrix([0, 1.75, 0])
    scene.add_geometry(stem, transform=transform, node_name="stem")
    for sign in [-1, 1]:
        leaf = trimesh.creation.icosphere(subdivisions=2, radius=1)
        leaf.apply_scale([.85, .35, .28])
        leaf.apply_transform(trimesh.transformations.rotation_matrix(sign * .45, [0, 0, 1]))
        leaf.visual.vertex_colors = [94, 168, 24, 255]
        scene.add_geometry(leaf, transform=trimesh.transformations.translation_matrix([sign * .65, 2.35, 0]), node_name=f"leaf_{sign}")
    path.parent.mkdir(parents=True, exist_ok=True)
    scene.export(str(path))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("output/minecraft/demo-sprout.glb"))
    args = parser.parse_args()
    make_demo(args.out)
    print(args.out)
