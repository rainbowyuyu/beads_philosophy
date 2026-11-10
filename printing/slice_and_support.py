"""Real mesh sections, teaching toolpaths and bed-connected support candidates.

No machine G-code is emitted. All processing coordinates are millimetres, Z up.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import GeometryCollection, LineString, Polygon


def positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def load_model(path: Path, units: str, up_axis: str, height_mm: float | None = None):
    """Preserve scene transforms before rotating, scaling and placing on the bed."""
    scene = trimesh.load_scene(path, process=True)
    mesh = scene.to_mesh()
    if mesh.is_empty or not np.isfinite(mesh.vertices).all():
        raise ValueError("The input has no finite triangular surface.")
    if up_axis == "y":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
    elif up_axis == "x":
        mesh.apply_transform(trimesh.transformations.rotation_matrix(-math.pi / 2, [0, 1, 0]))
    mesh.apply_scale({"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}[units])
    if height_mm is not None:
        if mesh.extents[2] <= 1e-10:
            raise ValueError("Cannot scale a zero-height mesh.")
        mesh.apply_scale(height_mm / mesh.extents[2])
    bounds = mesh.bounds
    mesh.apply_translation([-bounds[:, 0].mean(), -bounds[:, 1].mean(), -bounds[0, 2]])
    # A closed oriented surface is necessary for meaningful inside/outside claims.
    if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
        raise ValueError("Use a closed, consistently oriented positive-volume mesh. Repair it in a modelling tool first.")
    if len(mesh.faces) > 1_000_000:
        raise ValueError("Mesh exceeds the teaching tool's 1,000,000 triangle limit; simplify first.")
    return mesh


def polygon_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for item in getattr(geometry, "geoms", []) for part in polygon_parts(item)]


def line_parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type in ("LineString", "LinearRing"):
        return [geometry]
    return [part for item in getattr(geometry, "geoms", []) for part in line_parts(item)]


def section_geometry(mesh, z):
    section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    result = GeometryCollection()
    if section is None:
        return result
    for loop in section.discrete:
        if len(loop) < 4 or np.linalg.norm(loop[0] - loop[-1]) > 1e-5:
            raise ValueError(f"Open section at z={z:g}; input needs repair.")
        ring = Polygon(loop[:, :2])
        if not ring.is_valid:
            raise ValueError(f"Self-intersecting section at z={z:g}; input needs repair.")
        # Even/odd parity handles nested rings (holes) regardless of winding.
        result = result.symmetric_difference(ring)
    return result


def make_slices(mesh, layer_height=1.0, line_width=0.8, infill_spacing=3.0):
    if min(layer_height, line_width, infill_spacing) <= 0:
        raise ValueError("Layer height, line width and infill spacing must be positive.")
    if infill_spacing < line_width:
        raise ValueError("Infill spacing must be at least the line width.")
    height = float(mesh.bounds[1, 2])
    layer_count = math.ceil(height / layer_height)
    if layer_count > 1200:
        raise ValueError("More than 1200 layers: increase layer height for this teaching preview.")
    layers = []
    for i in range(layer_count):
        bottom, top = i * layer_height, min((i + 1) * layer_height, height)
        z = (bottom + top) / 2
        material = section_geometry(mesh, z)
        contours, paths = [], []
        for poly in polygon_parts(material):
            contours.append({"outer": np.asarray(poly.exterior.coords).round(6).tolist(),
                             "holes": [np.asarray(r.coords).round(6).tolist() for r in poly.interiors]})
        inset = material.buffer(-line_width / 2, join_style=2)
        for poly in polygon_parts(inset):
            for ring in [poly.exterior, *poly.interiors]:
                paths.append({"type": "perimeter", "closed": True,
                              "points": np.asarray(ring.coords).round(6).tolist()})
        infill = material.buffer(-line_width, join_style=2)
        if not infill.is_empty:
            xmin, ymin, xmax, ymax = infill.bounds
            low, high = (ymin, ymax) if i % 2 == 0 else (xmin, xmax)
            start = math.ceil(low / infill_spacing) * infill_spacing
            for lane, q in enumerate(np.arange(start, high + 1e-8, infill_spacing)):
                sweep = (LineString([(xmin - 1, q), (xmax + 1, q)]) if i % 2 == 0
                         else LineString([(q, ymin - 1), (q, ymax + 1)]))
                for segment in line_parts(sweep.intersection(infill)):
                    points = np.asarray(segment.coords)
                    if lane % 2:
                        points = points[::-1]
                    if segment.length > 1e-6:
                        paths.append({"type": "infill", "closed": False, "points": points.round(6).tolist()})
        distance = sum(float(np.linalg.norm(np.diff(p["points"], axis=0), axis=1).sum()) for p in paths)
        layers.append({"index": i, "slice_z_mm": round(z, 6), "print_z_mm": round(top, 6),
                       "height_mm": round(top - bottom, 6), "section_area_mm2": float(material.area),
                       "contours": contours, "paths": paths, "deposition_length_mm": distance})
    return layers


def make_supports(mesh, spacing=4.0, radius=0.6, angle=45.0, gap=0.25):
    """Find accessible underside sites and test vertical cylinder clearance.

    This deliberately emits only build-plate-connected candidates. A location
    requiring a support on another part of the model is recorded as rejected.
    Clearance is sampled at the centre and 16 circumference points, not claimed
    to be an exact mesh/solid Boolean collision test.
    """
    if spacing < 2 * radius or radius <= 0 or spacing <= 0 or gap < 0 or not 0 < angle < 90:
        raise ValueError("Need spacing >= 2*radius > 0, gap >= 0 and 0 < angle < 90.")
    downward = mesh.face_normals[:, 2] < -math.sin(math.radians(angle))
    candidates = np.flatnonzero(downward & (mesh.triangles_center[:, 2] > gap + 1e-6))
    accepted, rejected = [], []
    if not len(candidates):
        return accepted, rejected, None
    projections = [Polygon(mesh.triangles[i, :, :2]) for i in candidates]
    from shapely.ops import unary_union
    from shapely.geometry import Point
    footprint = unary_union([p for p in projections if p.area > 1e-10])
    if footprint.is_empty:
        return accepted, rejected, None
    xmin, ymin, xmax, ymax = footprint.bounds
    xs = np.arange(math.ceil(xmin / spacing) * spacing, xmax + 1e-8, spacing)
    ys = np.arange(math.ceil(ymin / spacing) * spacing, ymax + 1e-8, spacing)
    if len(xs) * len(ys) > 30_000:
        raise ValueError("More than 30000 support grid sites; increase support spacing.")
    sites = [(float(x), float(y)) for x in xs for y in ys if footprint.contains(Point(x, y))]
    if not sites:
        return accepted, rejected, None
    top = float(mesh.bounds[1, 2]) + 1

    def hits_xy(points):
        origins = np.column_stack([points, np.full(len(points), top)])
        directions = np.tile([0, 0, -1], (len(points), 1))
        locations, rays, faces = mesh.ray.intersects_location(origins, directions, multiple_hits=True)
        hits = [[] for _ in points]
        for loc, ray, face in zip(locations, rays, faces):
            hits[int(ray)].append((float(loc[2]), int(face)))
        return [sorted(row) for row in hits]

    center_hits = hits_xy(np.asarray(sites))
    sample_angles = np.linspace(0, 2 * math.pi, 16, endpoint=False)
    for (x, y), intersections in zip(sites, center_hits):
        eligible = [(z, face) for z, face in intersections if downward[face] and z > gap + 1e-6]
        if not eligible:
            continue
        contact_z, face = min(eligible)
        support_top = contact_z - gap
        # Any solid below the candidate contact blocks a bed-connected column.
        if intersections and intersections[0][0] < support_top - 1e-5:
            rejected.append({"xy_mm": [x, y], "contact_z_mm": contact_z, "reason": "model_below_contact"})
            continue
        ring = np.column_stack([x + radius * np.cos(sample_angles), y + radius * np.sin(sample_angles)])
        ring_hits = hits_xy(ring)
        if any(row and row[0][0] < support_top - 1e-5 for row in ring_hits):
            rejected.append({"xy_mm": [x, y], "contact_z_mm": contact_z, "reason": "sampled_pillar_collision"})
            continue
        accepted.append({"xy_mm": [x, y], "bottom_z_mm": 0.0, "top_z_mm": support_top,
                         "contact_z_mm": contact_z, "radius_mm": radius, "source_face": face,
                         "overhang_degrees_from_vertical": math.degrees(math.asin(-mesh.face_normals[face, 2]))})
    cylinders = []
    for column in accepted:
        cylinder = trimesh.creation.cylinder(radius=radius, height=column["top_z_mm"], sections=16)
        cylinder.apply_translation([*column["xy_mm"], column["top_z_mm"] / 2])
        cylinders.append(cylinder)
    support_mesh = trimesh.util.concatenate(cylinders) if cylinders else None
    return accepted, rejected, support_mesh


def export_preview(output, mesh, data):
    # Limit only the faint context wireframe; all exported slice paths are retained.
    edges = mesh.edges_unique
    if len(edges) > 9000:
        edges = edges[np.linspace(0, len(edges) - 1, 9000, dtype=int)]
    payload = dict(data)
    payload["context_edges"] = mesh.vertices[edges].round(5).tolist()
    template = (Path(__file__).parent / "viewer.html").read_text(encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    (output / "preview.html").write_text(template.replace("/*DATA*/ null", encoded), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--units", choices=["mm", "cm", "m", "in"], default="mm", help="source mesh units; GLB commonly uses metres")
    parser.add_argument("--up-axis", choices=["x", "y", "z"], default="z", help="source up axis; glTF/GLB convention is Y")
    parser.add_argument("--height-mm", type=positive, help="optional explicit target height after axis conversion")
    parser.add_argument("--layer-height", type=positive, default=1.0)
    parser.add_argument("--line-width", type=positive, default=0.8)
    parser.add_argument("--infill-spacing", type=positive, default=3.0)
    parser.add_argument("--support-spacing", type=positive, default=4.0)
    parser.add_argument("--support-radius", type=positive, default=0.6)
    parser.add_argument("--overhang-angle", type=positive, default=45.0, help="surface inclination away from build vertical, in degrees")
    parser.add_argument("--contact-gap", type=positive, default=0.25)
    args = parser.parse_args()
    try:
        mesh = load_model(args.input, args.units, args.up_axis, args.height_mm)
        layers = make_slices(mesh, args.layer_height, args.line_width, args.infill_spacing)
        supports, rejected, support_mesh = make_supports(mesh, args.support_spacing, args.support_radius, args.overhang_angle, args.contact_gap)
    except (ValueError, OSError, ImportError) as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=True)
    support_file = args.output / "supports.stl"
    if support_mesh is not None:
        support_mesh.export(support_file)
    elif support_file.exists():
        # Avoid leaving a stale support mesh from a previous invocation.
        raise SystemExit("No supports in this run, but supports.stl already exists. Choose a fresh output directory.")
    mesh.export(args.output / "normalized-model.stl")
    data = {"schema_version": 1, "purpose": "educational_geometry_not_printer_instructions", "units": "mm", "up": "+Z",
            "source_file": args.input.name, "source_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
            "bounds_mm": mesh.bounds.tolist(), "triangles": len(mesh.faces), "layer_height_mm": args.layer_height,
            "line_width_mm": args.line_width, "infill_spacing_mm": args.infill_spacing,
            "support_settings": {"spacing_mm": args.support_spacing, "radius_mm": args.support_radius,
                                 "overhang_degrees_from_vertical": args.overhang_angle, "contact_gap_mm": args.contact_gap,
                                 "landing": "build_plate_only", "clearance": "centre_plus_16_circumference_vertical_rays"},
            "layers": layers, "supports": supports, "rejected_support_sites": rejected,
            "support_stl": "supports.stl" if support_mesh is not None else None}
    (args.output / "simulation.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    export_preview(args.output, mesh, data)
    print(json.dumps({"layers": len(layers), "paths": sum(len(l["paths"]) for l in layers),
                      "supports": len(supports), "rejected_support_sites": len(rejected),
                      "preview": str(args.output / "preview.html")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
