"""Rigid back plate (PETG): flat inner face, 45-degree edge bevel captured by the bumper rim,
camera collar, and an optional terraced topographic relief.

Printed inner-face-down, so the collar and the relief grow upward and need no support.
"""

from __future__ import annotations

import build123d as bd

from .geom import face_from_polygon, outline, prism, ruled, stadium
from .params import CASE, PHONE, Case, Phone


def collar_size(p: Phone, c: Case) -> tuple[float, float]:
    """Outer length and height of the camera collar."""
    k = 2 * (c.collar_clear + c.collar_wall)
    return p.cam_len + k, p.cam_h + k


def plate_blank(p: Phone, c: Case, grow: float = 0.0) -> bd.Part:
    """Plate slab with its edge bevel. `grow` > 0 gives the matching pocket in the bumper."""
    t_v = c.plate_t - c.plate_bevel  # straight part of the edge, next to the phone
    d = c.plate_inset - grow
    z_in = grow if grow > 0 else 0.0
    z_out = -c.plate_t - grow
    run = (z_out - (-t_v)) * -1.0  # 45 degrees: run equals rise
    lower = prism(outline(p, d), -t_v, z_in)
    bevel = ruled(outline(p, d), -t_v, outline(p, d + run), z_out)
    return lower + bevel


def plate(p: Phone = PHONE, c: Case = CASE, relief=None) -> bd.Part:
    """The back plate. `relief` is a list of shapely (Multi)Polygons, one per terrace level."""
    body = plate_blank(p, c)

    cl, ch = collar_size(p, c)
    z_top = c.collar_top(p)
    collar = prism(bd.Pos(0, p.cam_y) * stadium(cl, ch), z_top, -c.plate_t + 0.01)
    collar = bd.fillet(collar.edges().group_by(bd.Axis.Z)[0], c.collar_fillet)
    body = body + collar

    if relief:
        z = -c.plate_t
        for level in relief:
            polys = list(getattr(level, "geoms", [level]))
            for poly in polys:
                face = face_from_polygon(poly)
                body = body + bd.Pos(0, 0, z + 0.01) * bd.extrude(face, c.topo_step + 0.01, dir=(0, 0, -1))
            z -= c.topo_step

    # Camera opening, with a 45-degree bevel on the collar's inner top edge (anti-glare).
    hl, hh = p.cam_len + 2 * c.collar_clear, p.cam_h + 2 * c.collar_clear
    hole = prism(bd.Pos(0, p.cam_y) * stadium(hl, hh), z_top - 1, 1)
    k = c.collar_chamfer
    bevel = ruled(bd.Pos(0, p.cam_y) * stadium(hl, hh), z_top + k,
                  bd.Pos(0, p.cam_y) * stadium(hl + 2 * (k + 0.3), hh + 2 * (k + 0.3)), z_top - 0.3)
    return body - hole - bevel
