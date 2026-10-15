"""Evenly spaced streamlines of a 2-D velocity snapshot (Jobard & Lefer 1997).

Lines are seeded `d_sep` apart and a line stops when it comes within `d_test` of
another line, or of itself (spirals, closed loops), or leaves the region, or
reaches a stagnation point. With `d_sep` equal to the extrusion spacing the
lines tile the surface without crossing, so they can be printed as toolpaths.
"""

from __future__ import annotations

from collections import deque

import numba as nb
import numpy as np
import shapely


@nb.njit(cache=True)
def _vel(vx, vy, x0, y0, h, x, y):
    fx = (x - x0) / h
    fy = (y - y0) / h
    i = int(np.floor(fx)); j = int(np.floor(fy))
    if i < 0 or j < 0 or i >= vx.shape[0] - 1 or j >= vx.shape[1] - 1:
        return 0.0, 0.0, False
    a = fx - i; b = fy - j
    u = (1 - a) * (1 - b) * vx[i, j] + a * (1 - b) * vx[i + 1, j] + (1 - a) * b * vx[i, j + 1] + a * b * vx[i + 1, j + 1]
    v = (1 - a) * (1 - b) * vy[i, j] + a * (1 - b) * vy[i + 1, j] + (1 - a) * b * vy[i, j + 1] + a * b * vy[i + 1, j + 1]
    return u, v, True


@nb.njit(cache=True)
def _dir(vx, vy, x0, y0, h, x, y, sgn, umin):
    u, v, ok = _vel(vx, vy, x0, y0, h, x, y)
    s = np.hypot(u, v)
    if not ok or s < umin:
        return 0.0, 0.0, False
    return sgn * u / s, sgn * v / s, True


@nb.njit(cache=True)
def _inside(mask, mx0, my0, mh, x, y):
    i = int((x - mx0) / mh); j = int((y - my0) / mh)
    if i < 0 or j < 0 or i >= mask.shape[0] or j >= mask.shape[1]:
        return False
    return mask[i, j]


@nb.njit(cache=True)
def _near(px, py, head, nxt, gx0, gy0, gh, gnx, gny, x, y, r):
    ci = int((x - gx0) / gh); cj = int((y - gy0) / gh)
    r2 = r * r
    for a in range(ci - 1, ci + 2):
        if a < 0 or a >= gnx:
            continue
        for b in range(cj - 1, cj + 2):
            if b < 0 or b >= gny:
                continue
            k = head[a * gny + b]
            while k >= 0:
                if (px[k] - x) ** 2 + (py[k] - y) ** 2 < r2:
                    return True
                k = nxt[k]
    return False


@nb.njit(cache=True)
def _trace(vx, vy, fx0, fy0, fh, mask, mx0, my0, mh, px, py, head, nxt, gx0, gy0, gh, gnx, gny,
           sx, sy, sgn, step, d_test, umin, max_n, skip, oth):
    """Integrate from (sx, sy) along sgn * velocity (RK4 on the unit direction field)."""
    buf = np.empty((max_n, 2))
    buf[0, 0] = sx; buf[0, 1] = sy
    n = 1
    x = sx; y = sy
    dt2 = d_test * d_test
    while n < max_n:
        k1x, k1y, ok1 = _dir(vx, vy, fx0, fy0, fh, x, y, sgn, umin)
        k2x, k2y, ok2 = _dir(vx, vy, fx0, fy0, fh, x + 0.5 * step * k1x, y + 0.5 * step * k1y, sgn, umin)
        k3x, k3y, ok3 = _dir(vx, vy, fx0, fy0, fh, x + 0.5 * step * k2x, y + 0.5 * step * k2y, sgn, umin)
        k4x, k4y, ok4 = _dir(vx, vy, fx0, fy0, fh, x + step * k3x, y + step * k3y, sgn, umin)
        if not (ok1 and ok2 and ok3 and ok4):
            break
        x = x + step * (k1x + 2 * k2x + 2 * k3x + k4x) / 6
        y = y + step * (k1y + 2 * k2y + 2 * k3y + k4y) / 6
        if not _inside(mask, mx0, my0, mh, x, y):
            break
        if _near(px, py, head, nxt, gx0, gy0, gh, gnx, gny, x, y, d_test):
            break
        hit = False
        for k in range(n - skip):
            if (buf[k, 0] - x) ** 2 + (buf[k, 1] - y) ** 2 < dt2:
                hit = True
                break
        for k in range(oth.shape[0]):  # the other half of the same line
            if (oth[k, 0] - x) ** 2 + (oth[k, 1] - y) ** 2 < dt2:
                hit = True
                break
        if hit:
            break
        buf[n, 0] = x; buf[n, 1] = y
        n += 1
    return buf[:n].copy()


class _Grid:
    def __init__(self, bounds, cell, cap=4_000_000):
        x0, y0, x1, y1 = bounds
        self.x0, self.y0, self.h = x0 - cell, y0 - cell, cell
        self.nx = int((x1 - x0) / cell) + 3
        self.ny = int((y1 - y0) / cell) + 3
        self.head = -np.ones(self.nx * self.ny, np.int64)
        self.nxt = -np.ones(cap, np.int64)
        self.px = np.empty(cap); self.py = np.empty(cap)
        self.n = 0

    def add(self, pts):
        for x, y in pts:
            c = int((x - self.x0) / self.h) * self.ny + int((y - self.y0) / self.h)
            k = self.n
            self.px[k] = x; self.py[k] = y
            self.nxt[k] = self.head[c]; self.head[c] = k
            self.n += 1

    def args(self):
        return self.px, self.py, self.head, self.nxt, self.x0, self.y0, self.h, self.nx, self.ny


def rasterize(region: shapely.Geometry, h: float = 0.05):
    """Boolean mask of `region` on a grid of pitch h; returns (mask, x0, y0, h)."""
    x0, y0, x1, y1 = region.bounds
    xs = np.arange(x0, x1 + h, h) + h / 2
    ys = np.arange(y0, y1 + h, h) + h / 2
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    shapely.prepare(region)
    mask = shapely.contains_xy(region, X.ravel(), Y.ravel()).reshape(X.shape)
    return mask, x0, y0, h


def evenly_spaced(xs, ys, v, region: shapely.Geometry, d_sep: float, d_test: float | None = None,
                  step: float = 0.12, min_len: float = 3.0, umin: float = 1e-4) -> list[np.ndarray]:
    """Streamlines of v = (vx, vy) on the grid (xs, ys) filling `region`, oriented with the flow."""
    if ys[0] > ys[-1]:
        ys = ys[::-1]; v = v[:, :, ::-1]
    vx = np.ascontiguousarray(v[0], np.float64); vy = np.ascontiguousarray(v[1], np.float64)
    fx0, fy0, fh = float(xs[0]), float(ys[0]), float(xs[1] - xs[0])
    umin = umin * float(np.nanmax(np.hypot(vx, vy)))
    d_test = 0.75 * d_sep if d_test is None else d_test
    mask, mx0, my0, mh = rasterize(region)
    grid = _Grid(region.bounds, d_sep)
    max_n = int(400 / step)
    skip = int(np.ceil(2.0 * d_sep / step)) + 2
    lines: list[np.ndarray] = []

    none = np.empty((0, 2))

    def trace(sx, sy):
        b = _trace(vx, vy, fx0, fy0, fh, mask, mx0, my0, mh, *grid.args(), sx, sy, 1.0, step, d_test, umin, max_n, skip, none)
        a = _trace(vx, vy, fx0, fy0, fh, mask, mx0, my0, mh, *grid.args(), sx, sy, -1.0, step, d_test, umin, max_n, skip,
                   np.ascontiguousarray(b[skip:]))
        return np.vstack([a[::-1], b[1:]])

    def length(pts):
        return float(np.hypot(*np.diff(pts, axis=0).T).sum()) if len(pts) > 1 else 0.0

    def accept(pts):
        lines.append(pts)
        grid.add(pts)
        queue.append(pts)

    def try_seed(sx, sy):
        if not _inside(mask, mx0, my0, mh, sx, sy):
            return
        if _near(*grid.args(), sx, sy, d_sep * 0.999):
            return
        pts = trace(sx, sy)
        if length(pts) >= min_len:
            accept(pts)

    queue: deque = deque()
    every = max(1, int(round(d_sep / step)))

    def drain():
        while queue:
            pts = queue.popleft()
            d = np.gradient(pts, axis=0)
            nrm = np.c_[-d[:, 1], d[:, 0]]
            nrm /= np.maximum(np.hypot(*nrm.T), 1e-12)[:, None]
            for k in range(0, len(pts), every):
                for s in (1.0, -1.0):
                    try_seed(*(pts[k] + s * d_sep * nrm[k]))

    # seed from a coarse grid until nothing more fits: the queue spreads each line to its neighbours
    x0, y0, x1, y1 = region.bounds
    for pitch in (8.0, 2.0, d_sep):
        for sy in np.arange(y1, y0, -pitch):
            for sx in np.arange(x0, x1, pitch):
                try_seed(sx, sy)
                drain()
    return lines


def streamfunction(xs, ys, v):
    """psi on the grid with vx = dpsi/dy, vy = -dpsi/dx (trapezoidal integration)."""
    if ys[0] > ys[-1]:
        ys = ys[::-1]; v = v[:, :, ::-1]
    vx, vy = v[0].astype(np.float64), v[1].astype(np.float64)
    dx = xs[1] - xs[0]; dy = ys[1] - ys[0]
    base = -np.concatenate([[0], np.cumsum(0.5 * (vy[1:, 0] + vy[:-1, 0]) * dx)])
    psi = base[:, None] + np.concatenate([np.zeros((len(xs), 1)), np.cumsum(0.5 * (vx[:, 1:] + vx[:, :-1]) * dy, axis=1)], axis=1)
    return xs, ys, psi
