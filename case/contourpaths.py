"""Toolpaths as level sets of one smooth scalar field, thinned by ordered dithering.

Level sets of one field never cross, and each runs unbroken until it leaves the region or
closes on itself, so lines break only where the spacing has to change. The field is
contoured at fine levels, Δ apart, and level m is drawn only where the local density needs
it: where f = Δ / (|∇s| d) is above its threshold t_m. The thresholds are bit-reversed
level indices (a 1-D ordered dither), so at any density the visible levels are spread as
evenly as fixed thresholds allow (gaps of two sizes at most, a factor 2 apart), and
neighbouring levels switch on at different places: where the flow spreads, new lines start
one by one, scattered along it, instead of in a row.
"""

from __future__ import annotations

import contourpy
import numpy as np
import shapely
from scipy.ndimage import map_coordinates


def _bitrev(m: np.ndarray, bits: int) -> np.ndarray:
    r = np.zeros_like(m)
    for b in range(bits):
        r |= ((m >> b) & 1) << (bits - 1 - b)
    return r


def _sample(grid: np.ndarray, xs, ys, pts: np.ndarray) -> np.ndarray:
    """Bilinear samples of grid[ix, iy] at points (x, y) in mm."""
    ix = (pts[:, 0] - xs[0]) / (xs[1] - xs[0])
    iy = (pts[:, 1] - ys[0]) / (ys[1] - ys[0])
    return map_coordinates(grid, [ix, iy], order=1, mode="nearest")


def _runs(on: np.ndarray, arc: np.ndarray, closed: bool, min_gap: float) -> list[tuple[int, int]]:
    """Index ranges [a, b] where `on`, with gaps shorter than min_gap bridged."""
    idx = np.flatnonzero(np.diff(np.r_[0, on.astype(np.int8), 0]))
    runs = [(int(a), int(b) - 1) for a, b in zip(idx[::2], idx[1::2])]
    merged: list[tuple[int, int]] = []
    for a, b in runs:
        if merged and arc[a] - arc[merged[-1][1]] < min_gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if closed and len(merged) > 1 and (arc[-1] - arc[merged[-1][1]]) + arc[merged[0][0]] < min_gap:
        merged[0] = (merged[-1][0] - len(on), merged[0][1])  # wraps across the seam
        merged.pop()
    return merged


def contour_paths(xs, ys, s: np.ndarray, region: shapely.Geometry, d: float, *, flow=None,
                  f_max: float = 1.0, max_levels: int = 2 ** 15, hyst: float = 0.15, min_len: float = 4.0,
                  min_loop: float = 2.5, min_gap: float = 3.0, seed: int = 1) -> tuple[list[np.ndarray], np.ndarray]:
    """Lines along the level sets of s[ix, iy] (xs, ys ascending), about d apart, inside region.

    f_max: the fine levels are spaced so that f reaches f_max at the 2nd percentile of the
    gradient; sparser places get every level and wider spacing. flow = (vx, vy) grids orient
    each line downstream. Returns the lines and the level value of each."""
    rng = np.random.default_rng(seed)
    gx = np.gradient(s, xs, axis=0)
    gy = np.gradient(s, ys, axis=1)
    G = np.hypot(gx, gy)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    shapely.prepare(region)
    inside = shapely.contains_xy(region, X.ravel(), Y.ravel()).reshape(X.shape)
    g_lo = max(np.percentile(G[inside], 2), 1e-9)
    s_lo, s_hi = s[inside].min(), s[inside].max()
    delta = max(f_max * d * g_lo, (s_hi - s_lo) / max_levels)
    bits = int(np.ceil(np.log2(max((s_hi - s_lo) / delta, 2))))
    M = 2 ** bits
    delta = (s_hi - s_lo) / M
    f = np.where(inside, delta / (np.maximum(G, 1e-12) * d), -1.0)  # -1: outside, always off
    offset = int(rng.integers(M))
    thresholds = (_bitrev((np.arange(M) + offset) % M, bits) + 0.5) / M
    gen = contourpy.contour_generator(xs, ys, s.T, line_type=contourpy.LineType.Separate)
    out, levels = [], []
    for m in np.argsort(thresholds):  # lowest thresholds first: the coarsest, everywhere-visible lines
        t = thresholds[m]
        if t * (1 - hyst) >= f.max():
            break
        level = s_lo + (m + 0.5) * delta
        for line in gen.lines(level):
            if len(line) < 3:
                continue
            closed = bool(np.allclose(line[0], line[-1]))
            ff = _sample(f, xs, ys, line)
            on, off = ff > t * (1 + hyst), ff < t * (1 - hyst)
            if not on.any():
                continue
            if closed and off.any():  # start the loop where it is off, so no run wraps
                k = int(np.flatnonzero(off)[0])
                line, ff, on, off = (np.roll(a, -k, axis=0) for a in (line[:-1], ff[:-1], on[:-1], off[:-1]))
                line, ff, on, off = (np.concatenate([a, a[:1]]) for a in (line, ff, on, off))
            decisive = on | off
            last = np.maximum.accumulate(np.where(decisive, np.arange(len(ff)), 0))
            state = np.where(decisive[last], on[last], False)
            if closed and not off.any():
                state[:] = True  # nothing turns this loop off
            arc = np.r_[0, np.cumsum(np.hypot(*np.diff(line, axis=0).T))]
            if closed and state.all():
                k = int(rng.integers(len(line) - 1))  # a closed loop starts anywhere
                pts = np.concatenate([line[k:-1], line[:k + 1]])
                pieces = [pts]
            else:
                pieces = []
                for a, b in _runs(state, arc, closed, min_gap):
                    seg = np.concatenate([line[a:], line[1:b + 1]]) if a < 0 else line[a:b + 1]
                    pieces.append(seg)
            for seg in pieces:
                if len(seg) < 2:
                    continue
                g = shapely.LineString(seg).intersection(region)
                for part in getattr(g, "geoms", [g]):
                    if part.is_empty or part.geom_type != "LineString":
                        continue
                    p = np.asarray(part.coords)
                    if part.length < (min_loop if np.allclose(p[0], p[-1]) else min_len):
                        continue
                    if flow is not None:
                        vx = _sample(flow[0], xs, ys, p); vy = _sample(flow[1], xs, ys, p)
                        tan = np.gradient(p, axis=0)
                        if np.sum(tan[:, 0] * vx + tan[:, 1] * vy) < 0:
                            p = p[::-1]
                    out.append(p)
                    levels.append(level)
    return out, np.asarray(levels)
