"""The streamline plate: flow snapshot -> evenly spaced streamlines -> G-code layer."""

from __future__ import annotations

import pathlib

import numpy as np
import shapely
import trimesh

from . import lbm, toolpath
from .contourpaths import contour_paths
from .params import Case, Phone
from .streamflow import snapshot
from .streamtrace import evenly_spaced, streamfunction

BED_CENTER = (125.0, 105.0)  # build.make_project slices with --center 125,105


def field(r: dict, phase: int, smooth: float):
    """The dye label (streaklines of a rake across the inlet) smoothed to the print's
    resolution, and the velocity, on ascending grids: xs, ys, s, (vx, vy)."""
    from scipy.ndimage import gaussian_filter

    xs, ys = r["xs"].astype(float), r["ys"].astype(float)
    v = r["shots"][phase].astype(float)
    dye = r["dye"][phase].astype(float)
    if ys[0] > ys[-1]:
        ys, v, dye = ys[::-1], v[:, :, ::-1], dye[:, ::-1]
    return xs, ys, gaussian_filter(dye, smooth / (xs[1] - xs[0]), mode="nearest"), (v[0], v[1])


def layer(p: Phone, c: Case, region: shapely.Geometry, em: float = 1.0, w: lbm.Wake | None = None) -> toolpath.Layer:
    width = c.stream_sep + c.stream_h * (1 - np.pi / 4)  # extruded width at this spacing
    area = region.buffer(-width / 2)  # line edges stay inside the region
    r = snapshot(p, c, c.stream_phase, w or lbm.Wake())
    if c.stream_source == "dye":
        xs, ys, s, flow = field(r, 0, c.dye_smooth)
        inner = area.buffer(-c.stream_sep)  # the outline bead runs along area's edge
        lines, vals = contour_paths(xs, ys, s, inner, c.stream_sep, flow=flow)
        o = np.argsort(vals, kind="stable")
        lines = [np.asarray(shapely.LineString(lines[k]).simplify(0.02).coords) for k in o]
        lines = toolpath.relax(lines, inner)
        vals = vals[o]
        frame = toolpath.outline(area)  # printed first, as its own colour piece
        lines = frame + lines
        vals = np.r_[np.full(len(frame), vals[0]), vals]
    else:  # instantaneous streamlines, evenly spaced (Jobard & Lefer)
        xs, ys = r["xs"].astype(float), r["ys"].astype(float)
        v = r["shots"][0].astype(float)
        lines = toolpath.close_loops(evenly_spaced(xs, ys, v, area, d_sep=c.stream_sep), c.stream_sep)
        lines, vals = toolpath.order(lines, streamfunction(xs, ys, v))
    lines = toolpath.subdivide(lines)
    spacing = toolpath.taper(lines, toolpath.local_spacing(lines, c.stream_sep), area)
    if c.stream_source == "dye":  # fill the holes left over, each in its neighbour's colour band
        lift = c.stream_h * (1 - np.pi / 4)
        fills = toolpath.gap_fill(lines, [sp + lift for sp in spacing], region.buffer(-0.3))
        for pts, w, k in fills:
            lines.append(toolpath.subdivide([pts])[0]); spacing.append(np.full(len(lines[-1]), w - lift))
            vals = np.r_[vals, vals[k]]
        o = np.argsort(vals, kind="stable")
        lines, spacing, vals = [lines[k] for k in o], [spacing[k] for k in o], vals[o]
    return toolpath.Layer(lines, vals, z=round(c.plate_t + c.stream_h, 4), h=c.stream_h, d_sep=c.stream_sep,
                          em=em, spacing=spacing, n_frame=len(frame) if c.stream_source == "dye" else 0)


def bed_transform(plate_stl: pathlib.Path):
    """Phone (x, y) -> bed (X, Y) for the plate as PrusaSlicer places it: the print
    orientation flips x (Rot 180 about y), then --center puts the bbox centre on BED_CENTER."""
    lo, hi = trimesh.load(plate_stl).bounds[:, :2]
    cx, cy = (lo + hi) / 2

    def to_bed(pts: np.ndarray) -> np.ndarray:
        return np.c_[-pts[:, 0] - cx + BED_CENTER[0], pts[:, 1] - cy + BED_CENTER[1]]

    return to_bed


def coverage(lyr: toolpath.Layer, region: shapely.Geometry) -> float:
    """Share of the region under a bead, with each segment at its own width."""
    segs = []
    for k, l in enumerate(lyr.lines):
        w = lyr.widths(k)
        ww = 0.5 * (w[1:] + w[:-1])
        segs += [shapely.LineString(l[i:i + 2]).buffer(ww[i] / 2, quad_segs=2) for i in range(len(l) - 1)]
    ink = shapely.unary_union(segs)
    return ink.intersection(region).area / region.area
