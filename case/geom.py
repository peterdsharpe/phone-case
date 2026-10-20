"""Small geometry helpers shared by the phone, bumper and plate models (build123d + shapely)."""

from __future__ import annotations

import math

import build123d as bd
import shapely

from .params import Phone


def rr(w: float, h: float, r: float) -> bd.Sketch:
    """Rounded rectangle centred on the origin."""
    return bd.RectangleRounded(w, h, max(min(r, w / 2 - 1e-3, h / 2 - 1e-3), 0.05))


def outline(p: Phone, inset: float, corner_r: float | None = None) -> bd.Sketch:
    """Phone plan outline shrunk by `inset` (negative grows it)."""
    r = (p.corner_r if corner_r is None else corner_r) - inset
    return rr(p.W - 2 * inset, p.L - 2 * inset, r)


def prism(sk: bd.Sketch | bd.Face, z0: float, z1: float) -> bd.Part:
    """Extrude a sketch drawn in the XY plane so it spans z0..z1."""
    return bd.Pos(0, 0, z0) * bd.extrude(sk, z1 - z0)


def ruled(sk0: bd.Sketch, z0: float, sk1: bd.Sketch, z1: float) -> bd.Part:
    """Straight-sided loft between two sketches with matching edge structure."""
    return bd.loft([bd.Plane.XY.offset(z0) * sk0, bd.Plane.XY.offset(z1) * sk1], ruled=True)


def stadium(length: float, height: float) -> bd.Sketch:
    """Pill shape `length` long (along local x) and `height` tall."""
    return bd.SlotOverall(length, height)


def side_plane(origin, outward, along) -> bd.Plane:
    """Plane on a side wall: local x runs `along` the wall, local z points `outward`."""
    return bd.Plane(origin=origin, x_dir=along, z_dir=outward)


def flared_cut(plane: bd.Plane, length: float, height: float, depth_in: float, depth_out: float, flare: float,
               shape=None) -> bd.Part:
    """Cutter for a side opening: straight from -depth_in to 0 (local z), then flaring
    by `flare` per side out to +depth_out. Openings widen toward the outside so a
    fingertip or cable plug can reach in. `shape(length, height)` gives the outline
    (a stadium by default)."""
    shape = shape or stadium
    straight = plane.offset(-depth_in) * shape(length, height)
    start = plane * shape(length, height)
    end = plane.offset(depth_out) * shape(length + 2 * flare, height + 2 * flare)
    inner = bd.extrude(straight, depth_in, dir=plane.z_dir)
    outer = bd.loft([start, end], ruled=True)
    return inner + outer


# ---- shapely twins (2-D, for the topographic relief) ---------------------------------------

def rr_shp(w: float, h: float, r: float, segs: int = 24) -> shapely.Polygon:
    r = max(min(r, w / 2 - 1e-3, h / 2 - 1e-3), 0.05)
    return shapely.box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r).buffer(r, quad_segs=segs)


def outline_shp(p: Phone, inset: float) -> shapely.Polygon:
    return rr_shp(p.W - 2 * inset, p.L - 2 * inset, p.corner_r - inset)


def stadium_shp(length: float, height: float, cx: float = 0.0, cy: float = 0.0) -> shapely.Polygon:
    a = (length - height) / 2
    return shapely.LineString([(cx - a, cy), (cx + a, cy)]).buffer(height / 2, quad_segs=24)


def face_from_polygon(poly: shapely.Polygon) -> bd.Face:
    """build123d face (with holes) from a shapely polygon in the XY plane (normal +z)."""
    poly = shapely.geometry.polygon.orient(poly, sign=1.0)

    def wire(ring):
        pts = list(ring.coords)[:-1]
        return bd.Wire.make_polygon([bd.Vector(x, y, 0) for x, y in pts], close=True)
    outer = wire(poly.exterior)
    holes = [wire(r) for r in poly.interiors]
    return bd.Face(outer, holes)


def deg(a: float) -> float:
    return math.degrees(a)
