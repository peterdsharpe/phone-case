"""Reference model of the Pixel 9 Pro XL, used to cut the case and for renders and fit checks."""

from __future__ import annotations

import build123d as bd

from .geom import prism, rr, stadium
from .params import PHONE, Phone


def phone_parts(p: Phone = PHONE) -> dict[str, bd.Part]:
    """Named solids: body, screen (thin overlay), camera bar, lens/flash dots, buttons."""
    body = prism(rr(p.W, p.L, p.corner_r), 0, p.T)
    body = bd.fillet(body.edges().group_by(bd.Axis.Z)[-1], p.edge_r)
    body = bd.fillet(body.edges().group_by(bd.Axis.Z)[0], p.edge_r)

    # Screen: a thin black overlay just proud of the glass, inset from the edge.
    screen = prism(rr(p.W - 2.4, p.L - 2.4, p.corner_r - 1.2), p.T - 0.02, p.T + 0.02)

    bar = prism(bd.Pos(0, p.cam_y) * stadium(p.cam_len, p.cam_h), -p.cam_proud, 0.0)
    bar = bd.fillet(bar.edges().group_by(bd.Axis.Z)[0], 0.8)

    # Three lenses on the left of the bar (seen from the back = +x side), flash/sensors on the right.
    lens_r = 6.4
    xs = [p.cam_len / 2 - 11.3, p.cam_len / 2 - 11.3 - 15.6, p.cam_len / 2 - 11.3 - 31.2]
    lenses = [bd.Pos(x, p.cam_y, -p.cam_proud - 0.02) * bd.Cylinder(lens_r, 0.06) for x in xs]
    flash = [bd.Pos(-p.cam_len / 2 + 9.0, p.cam_y + 3.5, -p.cam_proud - 0.02) * bd.Cylinder(2.2, 0.06),
             bd.Pos(-p.cam_len / 2 + 9.0, p.cam_y - 3.8, -p.cam_proud - 0.02) * bd.Cylinder(2.0, 0.06)]

    def button(top: float, length: float) -> bd.Part:
        y = p.from_top(top + length / 2)
        b = bd.Pos(p.W / 2 + (p.btn_proud - 0.6) / 2, y, p.T / 2) * bd.Box(p.btn_proud + 0.6, length, p.btn_h)
        return bd.fillet(b.edges().group_by(bd.Axis.X)[-1], 0.35)

    return {
        "body": body,
        "screen": screen,
        "bar": bar,
        "lenses": bd.Compound(lenses + flash),
        "buttons": button(p.power_top, p.power_len) + button(p.vol_top, p.vol_len),
    }


def phone_solid(p: Phone = PHONE) -> bd.Part:
    """Phone as one solid (body + camera bar + buttons) for interference checks."""
    parts = phone_parts(p)
    return parts["body"] + parts["bar"] + parts["buttons"]
