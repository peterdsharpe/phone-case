"""Streamline top layer: custom toolpaths spliced into PrusaSlicer's G-code.

The plate is sliced as usual with a flat back. One extra layer, `h` thick, is then
printed on the visible back face with its lines laid along the streamlines of the
collar's wake. Lines are printed in order of stream function, each in the flow
direction, so filament fed in coloured pieces makes coloured stream tubes, like
dye released from an upstream rake.
"""

from __future__ import annotations

import math
import pathlib
import re
from dataclasses import dataclass

import numpy as np
import shapely

A_FIL = math.pi * 1.75 ** 2 / 4  # mm^2

# Colour pieces for the streamline layer: (title, base colour, [(name, hex), ...] cycled in
# print order). Translucent over a black base reads as dark grey.
PALETTES = {
    "petg": ("PETG: white, Galaxy Black, translucent", "#1c1d24",
             [("white", "#ecebe6"), ("Galaxy Black", "#1c1d24"), ("white", "#ecebe6"), ("translucent", "#454b57")]),
    "pla_gold": ("PLA: gold, white, red, black", "#151515",
                 [("gold", "#c9a43c"), ("white", "#ecebe6"), ("matte red", "#a3262a"), ("black", "#151515")]),
}


@dataclass
class Layer:
    lines: list[np.ndarray]  # phone mm, each oriented with the flow, in print order
    psi: np.ndarray  # stream function of each line (print order is ascending)
    z: float  # top of the layer (print frame)
    h: float  # layer height
    d_sep: float  # nominal line spacing
    em: float = 1.0  # extrusion multiplier
    spacing: list[np.ndarray] | None = None  # local spacing at each point (variable width)
    n_frame: int = 0  # leading lines that outline the window: their own colour piece

    def __post_init__(self):
        if self.spacing is None:
            self.spacing = [np.full(len(l), self.d_sep) for l in self.lines]

    def seg_e(self, k: int) -> np.ndarray:
        """Filament (mm) for each segment of line k: the bead fills its strip of the layer."""
        l, sp = self.lines[k], self.spacing[k]
        return np.hypot(*np.diff(l, axis=0).T) * 0.5 * (sp[1:] + sp[:-1]) * self.h * self.em / A_FIL

    def widths(self, k: int) -> np.ndarray:
        """Extruded width at each point of line k (rectangle with round ends at spacing s)."""
        return self.spacing[k] + self.h * (1 - math.pi / 4)

    def filament(self) -> np.ndarray:
        """Cumulative filament length (mm) at the end of each line."""
        return np.cumsum([self.seg_e(k).sum() for k in range(len(self.lines))])


def _sides(lines: list[np.ndarray], step: float = 0.2, k_nn: int = 48):
    """Distance from each point to the nearest other line on its left and on its right
    (inf if none within 2 mm), sampled every `step` mm along each line. Returns per line
    (arc of the samples, arc of the vertices, left, right)."""
    from scipy.spatial import cKDTree

    dense, arcs = [], []
    for l in lines:
        d = np.r_[0, np.cumsum(np.hypot(*np.diff(l, axis=0).T))]
        a = np.arange(0, d[-1] + 1e-9, step)
        dense.append(np.c_[np.interp(a, d, l[:, 0]), np.interp(a, d, l[:, 1])]); arcs.append((a, d))
    P = np.vstack(dense)
    lid = np.concatenate([np.full(len(q), k) for k, q in enumerate(dense)])
    idx = np.concatenate([np.arange(len(q)) for q in dense])
    T = np.concatenate([np.gradient(q, axis=0) if len(q) > 1 else np.array([[1.0, 0.0]]) for q in dense])
    T /= np.maximum(np.hypot(*T.T), 1e-12)[:, None]
    dist, nb = cKDTree(P).query(P, k=k_nn, distance_upper_bound=2.0)
    ok = np.isfinite(dist)
    nb = np.where(ok, nb, 0)
    ok &= ~((lid[nb] == lid[:, None]) & (np.abs(idx[nb] - idx[:, None]) < int(3.0 / step)))
    dx = P[nb] - P[:, None, :]
    cr = T[:, None, 0] * dx[..., 1] - T[:, None, 1] * dx[..., 0]
    left = np.where(ok & (cr > 0), dist, np.inf).min(1)
    right = np.where(ok & (cr < 0), dist, np.inf).min(1)
    out, i0 = [], 0
    for (a, d), q in zip(arcs, dense):
        out.append((a, d, left[i0:i0 + len(q)], right[i0:i0 + len(q)]))
        i0 += len(q)
    return out


def _smooth(v: np.ndarray, n: int) -> np.ndarray:
    if len(v) <= n:
        return np.full_like(v, v.mean())
    return np.convolve(np.pad(v, n // 2, mode="edge"), np.ones(n) / n, mode="valid")[: len(v)]


def local_spacing(lines: list[np.ndarray], d_sep: float, lo: float = 0.42, hi: float = 0.95) -> list[np.ndarray]:
    """Centre-to-centre distance to the neighbouring line on each side, averaged: the width
    of the strip each point of each line has to fill. Sides with no neighbour (the region's
    edge) keep the nominal spacing."""
    out = []
    for a, d, left, right in _sides(lines):
        v = 0.5 * (np.where(np.isfinite(left), left, d_sep) + np.where(np.isfinite(right), right, d_sep))
        out.append(np.interp(d, a, _smooth(np.clip(v, lo, hi), 5)))
    return out


def relax(lines: list[np.ndarray], area: shapely.Geometry, iters: int = 3, alpha: float = 0.5,
          max_step: float = 0.12, smooth_mm: float = 2.0) -> list[np.ndarray]:
    """Shift each line sideways toward the middle of its strip (half the left/right imbalance
    per pass, at most max_step mm), so beads, which are symmetric about their path, can fill
    both sides. Two neighbours each close at most a quarter of the gap between them, so lines
    cannot cross; shifts are smoothed along the line and points stay inside `area`."""
    shapely.prepare(area)
    for _ in range(iters):
        new = []
        for l, (a, d, left, right) in zip(lines, _sides(lines)):
            L = np.where(np.isfinite(left), left, np.where(np.isfinite(right), right, 0.0))
            R = np.where(np.isfinite(right), right, L)
            sh = np.clip(alpha * (L - R) / 2, -max_step, max_step)
            sh = np.interp(d, a, _smooth(sh, max(1, int(smooth_mm / 0.2))))
            t = np.gradient(l, axis=0)
            t /= np.maximum(np.hypot(*t.T), 1e-12)[:, None]
            q = l + np.c_[-t[:, 1], t[:, 0]] * sh[:, None]
            keep = shapely.contains_xy(area, q[:, 0], q[:, 1])
            q[~keep] = l[~keep]
            if np.hypot(*(l[-1] - l[0])) < 1e-9:  # closed loops stay closed
                q[-1] = q[0]
            new.append(q)
        lines = new
    return lines


def gap_fill(lines: list[np.ndarray], widths: list[np.ndarray], area: shapely.Geometry, min_area: float = 0.4,
             min_len: float = 1.0, lo: float = 0.45, hi: float = 1.0) -> list[tuple[np.ndarray, float, int]]:
    """Short beads for the holes the lines leave (lens shapes at saddles, wedges at the edge),
    as PrusaSlicer's gap fill does: one bead along each hole's long axis, as wide as the hole.
    Returns (polyline, width, index of the nearest line) for each."""
    segs = []
    for l, w in zip(lines, widths):
        ww = 0.5 * (w[1:] + w[:-1])
        segs += [shapely.LineString(l[i:i + 2]).buffer(ww[i] / 2, quad_segs=2) for i in range(len(l) - 1)]
    holes = area.difference(shapely.unary_union(segs))
    tree = shapely.STRtree([shapely.LineString(l) for l in lines])
    out = []
    for g in getattr(holes, "geoms", [holes]):
        if g.geom_type != "Polygon" or g.area < min_area:
            continue
        box = np.asarray(g.minimum_rotated_rectangle.exterior.coords)[:4]
        e1, e2 = box[1] - box[0], box[2] - box[1]
        long_, short = (e1, e2) if np.hypot(*e1) >= np.hypot(*e2) else (e2, e1)
        mid = box.mean(0)
        axis = shapely.LineString([mid - long_ * 0.6, mid + long_ * 0.6]).intersection(g)
        for part in getattr(axis, "geoms", [axis]):
            if part.geom_type != "LineString" or part.length < min_len:
                continue
            width = float(np.clip(g.area / max(part.length, 1e-9), lo, hi))
            out.append((np.asarray(part.coords), width, int(tree.nearest(part.centroid))))
    return out


def outline(area: shapely.Geometry, seed: int = 2) -> list[np.ndarray]:
    """One closed bead around each edge of the region, starting at a random point."""
    rng = np.random.default_rng(seed)
    rings = []
    for poly in getattr(area, "geoms", [area]):
        for ring in [poly.exterior, *poly.interiors]:
            pts = np.asarray(ring.simplify(0.02).coords)[:-1]
            k = int(rng.integers(len(pts)))
            pts = np.roll(pts, -k, axis=0)
            rings.append(np.vstack([pts, pts[:1]]))
    return rings


def taper(lines: list[np.ndarray], spacing: list[np.ndarray], region: shapely.Geometry, length: float = 1.5,
          start: float = 0.6) -> list[np.ndarray]:
    """Thin each line's free ends (where a line starts or stops mid-surface) from `start` x
    its width to full width over `length` mm, so new lines emerge instead of starting at full
    width. Ends on the region's edge and closed loops keep full width."""
    edge = region.boundary
    out = []
    for l, sp in zip(lines, spacing):
        arc = np.r_[0, np.cumsum(np.hypot(*np.diff(l, axis=0).T))]
        f = np.ones(len(l))
        if np.hypot(*(l[-1] - l[0])) > 1e-6:  # open line
            for end, d in ((l[0], arc), (l[-1], arc[-1] - arc)):
                if shapely.distance(edge, shapely.Point(end)) > 0.6:
                    f = np.minimum(f, start + (1 - start) * np.clip(d / length, 0, 1))
        out.append(sp * f)
    return out


def subdivide(lines: list[np.ndarray], max_len: float = 1.0) -> list[np.ndarray]:
    """Split long segments so the width can change along them."""
    out = []
    for l in lines:
        seg = np.hypot(*np.diff(l, axis=0).T)
        n = np.maximum(1, np.ceil(seg / max_len).astype(int))
        pts = [l[:1]]
        for (a, b), m in zip(zip(l[:-1], l[1:]), n):
            t = np.arange(1, m + 1)[:, None] / m
            pts.append(a + t * (b - a))
        out.append(np.vstack(pts))
    return out


def close_loops(lines: list[np.ndarray], d_sep: float, seed: int = 1) -> list[np.ndarray]:
    """Close lines that end where they began (streamlines circling a vortex), and start each
    at a pseudo-random point, so the start/stop points of nested loops do not line up into a
    visible radial seam."""
    rng = np.random.default_rng(seed)
    out = []
    for l in lines:
        gap = np.hypot(*(l[-1] - l[0]))
        length = np.hypot(*np.diff(l, axis=0).T).sum()
        if len(l) > 10 and gap < 1.6 * d_sep and length > 4 * d_sep:
            k = int(rng.integers(len(l)))
            l = np.vstack([l[k:], l[:k], l[k:k + 1]])
        out.append(l)
    return out


def order(lines: list[np.ndarray], psi_grid, simplify: float = 0.02) -> tuple[list[np.ndarray], np.ndarray]:
    """Sort lines by their median stream function; simplify each polyline."""
    from scipy.interpolate import RegularGridInterpolator

    xs, ys, psi = psi_grid
    if ys[0] > ys[-1]:
        ys, psi = ys[::-1], psi[:, ::-1]
    f = RegularGridInterpolator((xs, ys), psi, bounds_error=False, fill_value=None)
    vals = np.array([np.median(f(l)) for l in lines])
    idx = np.argsort(vals)
    out = []
    for i in idx:
        g = shapely.LineString(lines[i]).simplify(simplify)
        out.append(np.asarray(g.coords))
    return out, vals[idx]


def bands(layer: Layer, n: int) -> list[tuple[int, int, float]]:
    """Split the print order into colour pieces: the window's outline (if any), then n bands
    of equal label range (equal widths of the inlet, as dye streams released side by side
    would be). Returns (first_line, end_line, filament_mm) per piece."""
    cum = np.concatenate([[0], layer.filament()])
    f0 = layer.n_frame
    out = [(0, f0, float(cum[f0]))] if f0 else []
    psi = layer.psi[f0:]
    edges = np.linspace(psi[0], psi[-1] + 1e-9, n + 1)
    for k in range(n):
        a = f0 + int(np.searchsorted(psi, edges[k], "left"))
        b = f0 + (int(np.searchsorted(psi, edges[k + 1], "left")) if k < n - 1 else len(psi))
        out.append((a, b, float(cum[b] - cum[a])))
    return out


@dataclass
class Machine:
    """Motion settings, taken from the PrusaSlicer config of the plate."""

    retract: float = 1.0
    retract_f: float = 2100
    deretract_f: float = 1500
    lift: float = 0.2
    travel_f: float = 10800
    z_f: float = 720
    print_f: float = 1800  # 30 mm/s: slow enough for neat, glossy lines
    min_travel_retract: float = 1.0

    @classmethod
    def from_config(cls, cfg: dict) -> "Machine":
        g = lambda k, d: float(str(cfg.get(k, d)).split(",")[0] or d)  # noqa: E731
        fr = str(cfg.get("filament_retract_length", "nil")).split(",")[0]
        fl = str(cfg.get("filament_retract_lift", "nil")).split(",")[0]
        return cls(retract=float(fr) if fr not in ("nil", "") else g("retract_length", 0.8),
                   retract_f=g("retract_speed", 35) * 60, deretract_f=(g("deretract_speed", 0) or g("retract_speed", 35)) * 60,
                   lift=float(fl) if fl not in ("nil", "") else g("retract_lift", 0.4),
                   travel_f=g("travel_speed", 180) * 60, z_f=g("travel_speed_z", 12) * 60 or 720,
                   min_travel_retract=g("retract_before_travel", 1))


def gcode_block(layer: Layer, to_bed, m: Machine, retracted: float, start_xy: tuple[float, float],
                change_before: bool, change_after: bool, park_xy: tuple[float, float] = (125.0, 12.0),
                color: str = "#ffffff") -> list[str]:
    """G-code for the layer. `retracted` is the retraction the block inherits and hands back.

    Colour changes follow PrusaSlicer's own pattern: M600 is called with the filament
    primed (the firmware unloads, reloads and purges, and hands back a primed nozzle)."""
    z = layer.z
    width = layer.d_sep + layer.h * (1 - math.pi / 4)
    out = [";STREAMLINE_LAYER_START", f";Z:{z:g}", f";HEIGHT:{layer.h:g}"]
    x, y = start_xy
    state = retracted  # mm of filament currently retracted

    def retract_to(target):
        nonlocal state
        if abs(target - state) > 1e-9:
            f = m.retract_f if target > state else m.deretract_f
            out.append(f"G1 E{-(target - state):.5f} F{f:.0f}")
            state = target

    for k, line in enumerate(layer.lines):
        pts = to_bed(line)
        es = layer.seg_e(k)
        sx, sy = pts[0]
        if math.hypot(sx - x, sy - y) > m.min_travel_retract or k == 0:
            retract_to(m.retract)
            out += [f"G1 Z{z + m.lift:.3f} F{m.z_f:.0f}", f"G1 X{sx:.3f} Y{sy:.3f} F{m.travel_f:.0f}",
                    f"G1 Z{z:.3f} F{m.z_f:.0f}"]
        else:
            out.append(f"G1 X{sx:.3f} Y{sy:.3f} F{m.travel_f:.0f}")
        retract_to(0.0)
        if k == 0:
            if change_before:
                out += [f";COLOR_CHANGE,T0,{color}", "M600", "G1 E0.4 ; prime after color change"]
            out += [";TYPE:Top solid infill", f";WIDTH:{width:.4f}", f";HEIGHT:{layer.h:g}"]
        out.append(f"G1 F{m.print_f:.0f}")  # every line: travel and deretract moves leave their own feedrate
        for (bx, by), e in zip(pts[1:], es):
            out.append(f"G1 X{bx:.3f} Y{by:.3f} E{e:.5f}")
        x, y = pts[-1]
    if change_after:  # park off the plate so the purge return cannot blob on the finished layer
        out += [f"G1 Z{z + m.lift:.3f} F{m.z_f:.0f}", f"G1 X{park_xy[0]:.3f} Y{park_xy[1]:.3f} F{m.travel_f:.0f}",
                ";COLOR_CHANGE,T0,#1c1d24", "M600"]
    retract_to(retracted)
    out += [f"G1 Z{z + m.lift:.3f} F{m.z_f:.0f}", ";STREAMLINE_LAYER_END"]
    return out


_E = re.compile(r"\bE(-?[\d.]+)")
_XY = re.compile(r"\b([XY])(-?[\d.]+)")


def splice(gcode: pathlib.Path, out: pathlib.Path, layer: Layer, to_bed, m: Machine, change_before=True,
           change_after=True) -> dict:
    """Insert the layer right after PrusaSlicer's AFTER_LAYER_CHANGE for z = layer.z."""
    lines = gcode.read_text().splitlines()
    tag = f";Z:{layer.z:g}"
    try:
        i = lines.index(tag)
    except ValueError:
        raise RuntimeError(f"no layer at {tag} in {gcode.name}; layer heights must land on it") from None
    j = lines.index(";AFTER_LAYER_CHANGE", i)
    j += 2  # skip the ";<z>" comment PrusaSlicer writes after it
    # Retraction inherited at this point: E moves since the last extrusion with XY motion.
    retracted, x, y = 0.0, 0.0, 0.0
    for s in lines[:j]:
        if s.startswith("G1"):
            xy = dict(_XY.findall(s)); e = _E.search(s)
            if "X" in xy: x = float(xy["X"])
            if "Y" in xy: y = float(xy["Y"])
            if e:
                de = float(e.group(1))
                if xy and de > 0:
                    retracted = 0.0
                else:
                    retracted -= de
        elif s.startswith("G92 E"):
            pass  # relative E: resets do not change the retraction state
    block = gcode_block(layer, to_bed, m, max(retracted, 0.0), (x, y), change_before, change_after)
    out.write_text("\n".join(lines[:j] + block + lines[j:]) + "\n")
    return dict(inserted_lines=len(block), inherited_retract=retracted, at_line=j) | block_stats(block, (x, y))


def block_stats(block: list[str], start_xy, accel: float = 1000.0) -> dict:
    """Filament, travel, peak flow and a time estimate for a block of G1 moves: travels and
    the first segment of each line accelerate from rest; later segments of a line keep speed
    (the toolpaths are smooth, so the firmware's junction handling does not slow them)."""
    x, y = start_xy
    f = 1800.0
    t = e_total = travel = peak = 0.0
    flowing = False
    for s in block:
        if not s.startswith("G1"):
            continue
        d = dict(re.findall(r"\b([XYZEF])(-?[\d.]+)", s.split(";")[0]))
        f = float(d.get("F", f))
        v = f / 60
        nx, ny = float(d.get("X", x)), float(d.get("Y", y))
        dist = math.hypot(nx - x, ny - y)
        e = float(d.get("E", 0))
        if dist > 0:
            ramp = v * v / accel  # distance spent accelerating and braking
            if e > 0 and flowing:
                t += dist / v
            else:
                t += dist / v + (v / accel if dist >= ramp else 2 * math.sqrt(dist / accel) - dist / v)
            flowing = e > 0
            if e > 0:
                e_total += e
                peak = max(peak, e * A_FIL / (dist / v))
            else:
                travel += dist
        elif "Z" in d:
            t += 0.2 / v + 0.05
            flowing = False
        elif e:
            t += abs(e) / v
            flowing = False
        x, y = nx, ny
    return dict(filament_mm=e_total, travel_m=travel / 1000, peak_mm3_s=peak, minutes=t / 60)


def mix(layer: Layer, pieces: list[tuple[str, float]], blend: float = 12.0, purge: float = 0.0):
    """Colour (rgb) at every point of every line for filament fed as `pieces` [(hex, mm), ...].

    The melt zone is modelled as a well-mixed volume with a 1/e length of `blend` mm of
    filament, so each colour fades into the next."""
    edges = np.cumsum([0] + [p[1] for p in pieces]) - purge
    rgb = np.array([[int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)] for c, _ in pieces])
    samples = []
    s = 0.0
    for k in range(len(layer.lines)):
        samples.append(s + np.r_[0, np.cumsum(layer.seg_e(k))])
        s = samples[-1][-1]
    grid = np.arange(0, s + 1, 0.25)
    idx = np.clip(np.searchsorted(edges, grid, "right") - 1, 0, len(pieces) - 1)
    feed = rgb[idx]
    a = 1 - np.exp(-0.25 / blend)
    out = np.empty_like(feed)
    c = feed[0].copy()
    for k in range(len(grid)):
        c += a * (feed[k] - c)
        out[k] = c
    return [np.stack([np.interp(sm, grid, out[:, ch]) for ch in range(3)], 1) for sm in samples]
