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


def flared_cut(plane: bd.Plane, length: float, height: float, depth_in: float, surface: float, r: float,
               shape=None, steps: int = 8) -> bd.Part:
    """Cutter for an opening in a wall whose outer face lies `surface` along the plane's normal
    (local z): straight from -depth_in, then rounded over into the outer face with radius r
    (a quarter-circle flare), so the opening widens toward the outside and leaves no sharp
    outer edge. `shape(length, height, grow)` gives the outline grown by `grow` per side
    (a stadium by default)."""
    shape = shape or (lambda w, h, g: stadium(w + 2 * g, h + 2 * g))
    s0 = surface - r
    inner = bd.extrude(plane.offset(-depth_in) * shape(length, height, 0.0), depth_in + s0, dir=plane.z_dir)
    phis = [0.47 * math.pi * k / (steps - 1) for k in range(steps)]  # to ~85 deg, where the arc meets the face
    secs = [plane.offset(s0 + r * math.sin(f)) * shape(length, height, r * (1 - math.cos(f))) for f in phis]
    secs.append(plane.offset(surface + 0.5) * shape(length, height, r + 2.0))  # out past the face, near-tangent
    return inner + bd.loft(secs, ruled=True)


def round_notch_corner(x0: float, xo: float, y: float, zs, r: float, side: int, flare: float, dz: int = 1,
                       steps: int = 8) -> bd.Part:
    """Cutter that rounds, with radius r, the convex edge along x where a notch's end face (at
    y, material on the -side side) meets a face at height zs(x): material above it for dz = +1,
    below it for dz = -1. It runs from x0 out through the outer face xo, following the notch's
    quarter-circle flare (radius `flare`, see flared_cut) near xo, so every y-z section is a
    right-angle corner rounded by r."""
    eps, c45 = 0.1, math.cos(math.pi / 4)

    def section(x: float, g: float, z0: float) -> bd.Face:
        ye = y - side * g
        P = lambda u, v: bd.Vector(x, u, v)  # noqa: E731
        cy, cz = ye - side * r, z0 + dz * r  # arc centre, r into the material
        pts = [P(cy, z0), P(cy, z0 - dz * eps), P(ye + side * eps, z0 - dz * eps), P(ye + side * eps, cz), P(ye, cz)]
        arc = bd.ThreePointArc(P(ye, cz), P(cy + side * r * c45, cz - dz * r * c45), P(cy, z0))
        return bd.Face(bd.Wire([*bd.Polyline(*pts).edges(), arc]))

    phis = [0.47 * math.pi * k / (steps - 1) for k in range(steps)]  # flared_cut's sections
    xs = [x0] + [xo - flare + flare * math.sin(f) for f in phis]
    gs = [0.0] + [flare * (1 - math.cos(f)) for f in phis]
    secs = [section(x, g, zs(x)) for x, g in zip(xs, gs)]
    secs.append(section(xo + 0.5, flare + 2.0, zs(xo + 0.5)))  # out past the face
    return bd.loft(secs, ruled=True)


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
