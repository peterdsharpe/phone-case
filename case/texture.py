"""Grip texture for the bumper's long sides: the back's flow, carried over the edges.

The lattice-Boltzmann wake behind the camera collar (case/lbm.py) is solved on a domain five
collar-widths wide, so the flow just beyond the phone's long edges belongs to the same
simulation as the flow printed on the back plate. Each side band shows the strip of that flow
it would cover if the back were unrolled over the bumper's rim and edge: grooves follow the
dye streaklines of the same snapshot, spaced about `grip_sep` apart by the plate's ordered
dithering (case/contourpaths.py), with a smooth cosine cross-section and tapered ends.

The texture lives in the print mesh only (a manifold boolean on the exported bumper), not in
the CAD: the STEP files keep plain sides.
"""

from __future__ import annotations

import functools

import numpy as np
import shapely
import trimesh
from scipy.ndimage import map_coordinates
from scipy.spatial import cKDTree

from .contourpaths import contour_paths
from .params import Case, Phone

FINE = 0.05  # mm, raster for the groove profile
EPS, SKIM, RAMP = 0.003, 0.02, 0.8  # mm: the cutter is EPS outside the wall at the band edge, SKIM inside within it


def _ramp(d, w):
    t = np.clip(d / w, 0, 1)
    return t * t * (3 - 2 * t)


def band_z(p: Phone, c: Case) -> tuple[float, float]:
    """Height range of the textured band on the side walls: TPU only (fused case: above the
    PETG back, below the flush top's chamfer), clear of the edges."""
    if c.style == "fused":
        return 0.3, p.T + c.fit_z - c.top_chamfer - 0.3
    return c.z_back + c.back_fillet + 0.3, c.z_front(p) - c.front_chamfer - 0.3


def unroll(p: Phone, c: Case) -> tuple[float, float]:
    """(a, zs): with the back unrolled over its edge (fused case: the base chamfer; two-part
    case: the rim and its back fillet), a side wall point at height z lies a + (z - zs) from
    the phone's centre line."""
    if c.style == "fused":
        b = c.base_chamfer
        return c.outer_W(p) / 2 - b + np.sqrt(2) * b, -c.back_t + b
    zs = c.z_back + c.back_fillet
    return c.outer_W(p) / 2 - c.back_fillet + np.pi / 2 * c.back_fillet, zs


def streaklines(p: Phone, c: Case, side: int) -> list[np.ndarray]:
    """The groove lines of one side, as (y, z) polylines on the side wall."""
    from .streamflow import snapshot
    from .streamplate import field
    from . import lbm

    z0, z1 = band_z(p, c)
    a, zs = unroll(p, c)
    ya, yb = c.grip_y
    xs, ys, s, flow = field(snapshot(p, c, c.stream_phase, lbm.Wake()), 0, c.dye_smooth)
    xa, xb = sorted((side * (a + z0 - zs), side * (a + z1 - zs)))
    assert xs[0] <= xa and xb <= xs[-1], "the stored flow does not reach the side bands (streamflow.SIDE_MARGIN)"
    region = shapely.box(xa, ya - 1.0, xb, yb + 1.0)
    lines, _ = contour_paths(xs, ys, s, region, c.grip_sep, flow=flow, min_len=5.0, min_loop=8.0)  # no dimples or specks
    return [np.c_[ln[:, 1], zs + side * ln[:, 0] - a] for ln in lines]


@functools.cache
def _raster(p: Phone, c: Case, side: int):
    """Groove depth (0..1) on a FINE grid over one side band: rows y, columns z."""
    z0, z1 = band_z(p, c)
    ya, yb = c.grip_y
    yg = np.arange(ya - 1.0, yb + 1.0 + FINE / 2, FINE)
    zg = np.arange(z0, z1 + FINE / 2, FINE)
    edge = shapely.box(yg[0], zg[0], yg[-1], zg[-1]).boundary
    pts, ends = [], []  # points along the lines, ~0.02 mm apart, and their distance along the line to a free end
    for ln in streaklines(p, c, side):
        seg = np.hypot(*np.diff(ln, axis=0).T)
        arc = np.concatenate([[0], np.cumsum(seg)])
        t = np.linspace(0, arc[-1], max(int(np.ceil(arc[-1] / 0.02)), 1) + 1)
        pts.append(np.c_[np.interp(t, arc, ln[:, 0]), np.interp(t, arc, ln[:, 1])])
        closed = np.allclose(ln[0], ln[-1])
        e = np.full(len(t), np.inf)
        if not closed and edge.distance(shapely.Point(ln[0])) > 0.5:  # ends at the band edges are not free
            e = np.minimum(e, t)
        if not closed and edge.distance(shapely.Point(ln[-1])) > 0.5:
            e = np.minimum(e, t[-1] - t)
        ends.append(e)
    pts, ends = np.concatenate(pts), np.concatenate([*ends, [np.inf]])  # index len(pts): no line in reach
    Y, Z = np.meshgrid(yg, zg, indexing="ij")
    half = c.grip_groove_w / 2
    dist, k = cKDTree(pts).query(np.c_[Y.ravel(), Z.ravel()], distance_upper_bound=half)
    prof = 0.5 * (1 + np.cos(np.pi * np.clip(dist / half, 0, 1)))  # meets the wall tangentially
    return yg, zg, (prof * _ramp(ends[k], c.grip_taper)).reshape(Y.shape)


def depth(p: Phone, c: Case, side: int, y: np.ndarray, z: np.ndarray, y0: float, y1: float) -> np.ndarray:
    """Groove depth (mm) at points (y, z) of one side's band, in a stretch y0..y1."""
    yg, zg, h01 = _raster(p, c, side)
    z0, z1 = band_z(p, c)
    h = map_coordinates(h01, [(y - yg[0]) / FINE, (z - zg[0]) / FINE], order=1, mode="nearest")
    taper = _ramp(np.minimum(y - y0, y1 - y), c.grip_taper) * _ramp(np.minimum(z - z0, z1 - z), c.grip_taper / 2)
    return c.grip_depth * h * taper


def bands(p: Phone, c: Case) -> list[tuple[int, float, float, float, float]]:
    """(side, y0, y1, z0, z1) for each textured stretch; side +1 is the button side."""
    z0, z1 = band_z(p, c)
    ya, yb = c.grip_y
    out = [(-1, ya, yb, z0, z1)]
    # Button side: skip the notch over the buttons.
    m = c.btn_margin + c.cut_round + c.grip_clear
    lo = p.from_top(p.vol_top + p.vol_len) - m
    hi = p.from_top(p.power_top) + m
    for a, b in ((ya, lo), (hi, yb)):
        if b - a > 2 * c.grip_taper:
            out.append((+1, a, b, z0, z1))
    return out


def _cutter(side: int, y0: float, y1: float, z0: float, z1: float, x_face: float, h, step: float) -> trimesh.Trimesh:
    """Closed slab from the textured surface (h below the wall) out past the wall. Over the band it
    also sits SKIM below the wall, so the whole band is retriangulated as one even grid (long
    fan triangles shade in streaks); within RAMP of the band's edge it rises to EPS outside the
    wall, crossing it at about 1.5 degrees: no step and no coplanar faces."""
    ys = np.linspace(y0, y1, max(2, int(np.ceil((y1 - y0) / step)) + 1))
    zs = np.linspace(z0, z1, max(2, int(np.ceil((z1 - z0) / step)) + 1))
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    H = h(Y, Z)
    edge = np.minimum(np.minimum(Y - y0, y1 - Y), np.minimum(Z - z0, z1 - Z))
    x_in = side * (x_face + EPS - (SKIM + EPS) * _ramp(edge, RAMP) - H)
    x_out = np.full_like(x_in, side * (x_face + 1.0))
    n = Y.size
    verts = np.vstack([np.c_[x_in.ravel(), Y.ravel(), Z.ravel()], np.c_[x_out.ravel(), Y.ravel(), Z.ravel()]])
    idx = np.arange(n).reshape(Y.shape)
    a, b, cc, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    Hf = H.ravel()
    ac = np.abs(Hf[a] - Hf[cc]) <= np.abs(Hf[b] - Hf[d])  # split each cell along the flatter diagonal: no zigzag on slanted grooves
    inner = np.r_[np.c_[a, b, cc][ac], np.c_[a, cc, d][ac], np.c_[a, b, d][~ac], np.c_[b, cc, d][~ac]]
    loop = np.r_[idx[:, 0], idx[-1, 1:], idx[-2::-1, -1], idx[0, -2:0:-1]]
    nxt = np.roll(loop, -1)
    walls = np.r_[np.c_[loop, nxt, nxt + n], np.c_[loop, nxt + n, loop + n]]
    m = trimesh.Trimesh(verts, np.vstack([inner, inner[:, ::-1] + n, walls]), process=False)
    trimesh.repair.fix_normals(m)
    assert m.is_watertight and m.is_volume, "texture cutter is not a closed solid"
    return m


def apply(bumper: trimesh.Trimesh, p: Phone, c: Case, step: float = 0.15) -> trimesh.Trimesh:
    """The bumper mesh with the flow's streaklines cut into both long sides."""
    x_face = c.outer_W(p) / 2
    cutters = []
    for side, y0, y1, z0, z1 in bands(p, c):
        cutters.append(_cutter(side, y0, y1, z0, z1, x_face,
                               lambda Y, Z, side=side, y0=y0, y1=y1: depth(p, c, side, Y, Z, y0, y1), step))
    out = trimesh.boolean.difference([bumper, *cutters], engine="manifold")
    assert out.is_watertight, "textured bumper is not watertight"
    return out
