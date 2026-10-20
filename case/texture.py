"""Grip texture for the bumper's long sides: Kelvin-Helmholtz billows.

A shear layer between two streams rolls up into a row of vortices. Stuart (1967) gives that
flow in closed form; dye lines that start out straight, carried by it for a while, wind into
the breaking-wave curls of Kelvin-Helmholtz billows. The grooves follow two of those lines.

The texture lives in the print mesh only (a manifold boolean on the exported bumper), not in
the CAD: the STEP files keep plain sides.
"""

from __future__ import annotations

import functools

import numpy as np
import trimesh
from scipy.ndimage import distance_transform_edt, map_coordinates

from .params import Case, Phone

FINE = 0.05  # mm, raster for the groove profile


def _stuart(x, y, C):
    s = np.sqrt(C * C - 1.0)
    d = C * np.cosh(y) - s * np.cos(x)
    return C * np.sinh(y) / d, -s * np.sin(x) / d


def _dye(xi, eta, C: float, T: float, steps: int = 300):
    """Each point's eta a time T earlier in the Stuart flow (vortices at xi = 0 mod 2 pi)."""
    x, y = xi.copy(), eta.copy()
    dt = -T / steps
    for _ in range(steps):  # RK4, backwards in time
        a = _stuart(x, y, C)
        b = _stuart(x + dt / 2 * a[0], y + dt / 2 * a[1], C)
        c = _stuart(x + dt / 2 * b[0], y + dt / 2 * b[1], C)
        d = _stuart(x + dt * c[0], y + dt * c[1], C)
        x += dt / 6 * (a[0] + 2 * b[0] + 2 * c[0] + d[0])
        y += dt / 6 * (a[1] + 2 * b[1] + 2 * c[1] + d[1])
    return y


@functools.cache
def _tile(lam: float, C: float, T: float, spacing: float, width: float, half_h: float) -> np.ndarray:
    """Groove depth (0..1) over one wavelength: rows u (along the side), columns v (across)."""
    nu = int(round(lam / FINE))
    u = np.arange(3 * nu) * FINE  # three periods, so the distance transform sees across the seams
    v = np.arange(-half_h, half_h + FINE / 2, FINE)
    U, V = np.meshgrid(u, v, indexing="ij")
    ell = lam / (2 * np.pi)
    s = _dye(2 * np.pi * U / lam, V / ell, C, T)
    lines = np.zeros(s.shape, bool)
    for level in (-spacing / 2, spacing / 2):  # the two dye lines nearest the shear layer's middle
        side = s > level
        lines[1:, :] |= side[1:, :] != side[:-1, :]
        lines[:, 1:] |= side[:, 1:] != side[:, :-1]
    dist = distance_transform_edt(~lines) * FINE
    prof = np.clip(1 - (dist / (width / 2)) ** 2, 0, 1)  # rounded groove
    return prof[nu:2 * nu]


def depth(c: Case, y: np.ndarray, z: np.ndarray, z0: float, z1: float, y0: float, y1: float) -> np.ndarray:
    """Groove depth (mm) at points (y, z) of a side band z0..z1, in a stretch y0..y1."""
    half_h = (z1 - z0) / 2
    tile = _tile(c.billow_lambda, c.billow_C, c.billow_T, c.billow_spacing, c.grip_groove_w, round(half_h, 3))
    nu, nv = tile.shape
    iu = np.mod(-y / FINE, nu)  # the billows travel toward -y, with the flow over the back
    iv = (z - (z0 + z1) / 2 + half_h) / FINE
    h = map_coordinates(np.pad(tile, ((0, 1), (0, 0)), mode="wrap"), [iu, iv], order=1, mode="nearest")

    def ramp(d, w):
        t = np.clip(d / w, 0, 1)
        return t * t * (3 - 2 * t)

    taper = ramp(np.minimum(y - y0, y1 - y), c.grip_taper) * ramp(np.minimum(z - z0, z1 - z), 0.25)
    return c.grip_depth * h * taper


def bands(p: Phone, c: Case) -> list[tuple[int, float, float, float, float]]:
    """(side, y0, y1, z0, z1) for each textured stretch; side +1 is the button side."""
    z0 = c.z_back + c.back_fillet + 0.3
    z1 = c.z_front(p) - c.front_chamfer - 0.3
    ya, yb = c.grip_y
    out = [(-1, ya, yb, z0, z1)]
    # Button side: skip the openings (and the short wall between power and volume).
    m = c.btn_margin + c.cut_flare + c.grip_clear
    lo = p.from_top(p.vol_top + p.vol_len) - m
    hi = p.from_top(p.power_top) + m
    for a, b in ((ya, lo), (hi, yb)):
        if b - a > 2 * c.grip_taper:
            out.append((+1, a, b, z0, z1))
    return out


def _cutter(side: int, y0: float, y1: float, z0: float, z1: float, x_face: float, h, step: float) -> trimesh.Trimesh:
    """Closed slab from the textured surface (x_face - 0.02 - h) out past the wall."""
    ys = np.linspace(y0, y1, max(2, int(np.ceil((y1 - y0) / step)) + 1))
    zs = np.linspace(z0, z1, max(2, int(np.ceil((z1 - z0) / step)) + 1))
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    x_in = side * (x_face - 0.02 - h(Y, Z))  # 20 um deeper than the wall everywhere: no coplanar faces
    x_out = np.full_like(x_in, side * (x_face + 1.0))
    n = Y.size
    verts = np.vstack([np.c_[x_in.ravel(), Y.ravel(), Z.ravel()], np.c_[x_out.ravel(), Y.ravel(), Z.ravel()]])
    idx = np.arange(n).reshape(Y.shape)
    a, b, cc, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    inner = np.r_[np.c_[a, b, cc], np.c_[a, cc, d]]
    loop = np.r_[idx[:, 0], idx[-1, 1:], idx[-2::-1, -1], idx[0, -2:0:-1]]
    nxt = np.roll(loop, -1)
    walls = np.r_[np.c_[loop, nxt, nxt + n], np.c_[loop, nxt + n, loop + n]]
    m = trimesh.Trimesh(verts, np.vstack([inner, inner[:, ::-1] + n, walls]), process=False)
    trimesh.repair.fix_normals(m)
    assert m.is_watertight and m.is_volume, "texture cutter is not a closed solid"
    return m


def apply(bumper: trimesh.Trimesh, p: Phone, c: Case, step: float = 0.15) -> trimesh.Trimesh:
    """The bumper mesh with billow grooves cut into both long sides."""
    x_face = c.outer_W(p) / 2
    cutters = []
    for side, y0, y1, z0, z1 in bands(p, c):
        cutters.append(_cutter(side, y0, y1, z0, z1, x_face,
                               lambda Y, Z, y0=y0, y1=y1, z0=z0, z1=z1: depth(c, Y, Z, z0, z1, y0, y1), step))
    out = trimesh.boolean.difference([bumper, *cutters], engine="manifold")
    assert out.is_watertight, "textured bumper is not watertight"
    return out
