"""The streamline plate: flow snapshot -> evenly spaced streamlines -> G-code layer."""

from __future__ import annotations

import pathlib

import numpy as np
import shapely
import trimesh

from . import toolpath
from .params import Case, Phone
from .streamflow import wake
from .streamtrace import evenly_spaced, streamfunction

BED_CENTER = (125.0, 105.0)  # build.make_project slices with --center 125,105


def layer(p: Phone, c: Case, region: shapely.Geometry, em: float = 1.0) -> toolpath.Layer:
    r = wake(p, c)
    xs, ys = r["xs"].astype(float), r["ys"].astype(float)
    v = r["shots"][c.stream_phase].astype(float)
    width = c.stream_sep + c.stream_h * (1 - np.pi / 4)  # extruded width at this spacing
    area = region.buffer(-width / 2)  # line edges stay inside the region
    lines = toolpath.close_loops(evenly_spaced(xs, ys, v, area, d_sep=c.stream_sep), c.stream_sep)
    lines, psi = toolpath.order(lines, streamfunction(xs, ys, v))
    lines = toolpath.subdivide(lines)
    spacing = toolpath.local_spacing(lines, c.stream_sep)
    return toolpath.Layer(lines, psi, z=round(c.plate_t + c.stream_h, 4), h=c.stream_h, d_sep=c.stream_sep,
                          em=em, spacing=spacing)


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
