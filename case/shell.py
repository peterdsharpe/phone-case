"""Fused case: the case and its back in one print, plus a separate camera ring.

The main part prints back-down. Its first layer is the hand-fed streamline layer (PETG: the
back's visible face), a few black PETG layers finish the back, and then the printer stops for
TPU and prints the walls on top in the same job. The camera ring is its own PETG part: it drops
in from the inside before the phone, and its flange sits in a recess in the back, where the
phone holds it.

Edges: the lip stays on the top edge and the four corners (the first things to land in a
drop); the long sides and the bottom stop at the screen, for edge-swipe gestures, with ramps
between. Printed back-down, every inward overhang is at most 45 degrees: the walls lean in at
45 degrees over the phone's rounded edge instead of curling over flat.

Phone frame (case/params.py): z = 0 on the back glass, +z toward the screen. The back spans
-back_t..0 and is PETG; everything above z = 0 is TPU.
"""

from __future__ import annotations

import math

import build123d as bd
import shapely

from .geom import flared_cut, outline, prism, round_notch_corner, rr, rr_shp, ruled, side_plane, stadium, stadium_shp
from .params import CASE, PHONE, Case, Phone
from .plate import collar_size

K45 = 1 - math.cos(math.pi / 4)  # a quarter-circle fillet turns 45 degrees this fraction of its radius in


def main_part(p: Phone = PHONE, c: Case = CASE) -> bd.Part:
    """Back and walls as one solid; split() divides it into the PETG and TPU volumes."""
    Wo, Lo = c.outer_W(p), c.outer_L(p)
    zb, zt = -c.back_t, c.z_front(p)
    f, T = c.fit, p.T + c.fit_z
    R = p.edge_r + f

    body = prism(rr(Wo, Lo, c.outer_corner_r), zb, zt)
    body = bd.chamfer(body.edges().group_by(bd.Axis.Z)[-1], c.top_chamfer)
    body = bd.chamfer(body.edges().group_by(bd.Axis.Z)[0], c.base_chamfer)

    # Phone cavity, hugging the rounded front edge; above the fillet's 45-degree point the wall
    # leans in at 45 degrees (the lip's underside), so nothing overhangs more than that.
    cav = prism(outline(p, -f), 0.0, T)
    cav = bd.fillet(cav.edges().group_by(bd.Axis.Z)[-1], R)
    z45 = T - K45 * R
    under = ruled(outline(p, -f + K45 * R), z45, outline(p, -f + K45 * R + 3.0), z45 + 3.0)
    # Corner air pockets (a ~1.3 mm gap at each phone corner), with a 45-degree roof at the
    # front end: their ceiling as printed.
    relief = prism(outline(p, -f, corner_r=c.corner_relief_r + f), c.corner_relief_margin, p.T - c.corner_relief_margin)
    relief = bd.chamfer(relief.edges().group_by(bd.Axis.Z)[-1], c.relief_roof)

    # Lip opening over the screen, with a small chamfer at the top.
    r_lip = p.corner_r - (c.lip_side + c.lip_end) / 2
    w0, l0 = p.W - 2 * c.lip_side, p.L - 2 * c.lip_end
    throat = prism(rr(w0, l0, r_lip), T - 1.0, zt + 1.0)
    k = c.lip_end_bevel
    bevel = ruled(rr(w0, l0, r_lip), zt - k, rr(w0 + 4 * k, l0 + 4 * k, r_lip + 2 * k), zt + k)

    # The back: an opening for the camera ring, and a recess for its flange.
    cl, ch = collar_size(p, c)
    g, fw = c.ring_clear, c.ring_flange
    hole = prism(bd.Pos(0, p.cam_y) * stadium(cl + 2 * g, ch + 2 * g), zb - 1.0, 0.5)
    recess = prism(bd.Pos(0, p.cam_y) * stadium(cl + 2 * (fw + g), ch + 2 * (fw + g)), -c.ring_flange_t, 0.5)

    for cut in [cav, under, relief, throat, bevel, *flush_cuts(p, c), hole, recess, *openings(p, c)]:
        body = body - cut
    return body


def split(body: bd.Part, p: Phone = PHONE, c: Case = CASE) -> tuple[bd.Part, bd.Part]:
    """(PETG back, TPU walls): the part below and above z = 0."""
    big = 2 * max(c.outer_W(p), c.outer_L(p))
    lo = bd.Pos(0, 0, -c.back_t - 1.0) * bd.Box(big, big, c.back_t + 1.0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    hi = bd.Box(big, big, c.z_front(p) + 1.0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return body & lo, body & hi


def flush_cuts(p: Phone, c: Case) -> list[bd.Part]:
    """Cut the long sides and the bottom down to the screen (edge-swipe gestures), keeping the
    lip on the top edge and the four corners, with a ramp at each end of each cut, and a chamfer
    on the outer edge."""
    f, T = c.fit, p.T + c.fit_z
    zt, ct = c.z_front(p), c.top_chamfer
    lift = zt - T + 0.02  # lifted this far, the profile clears the lip's top and its chamfer

    def profile(u_c: float, u_o: float, dz: float) -> list[tuple[float, float]]:
        """(u, z) outline of the cut across a wall, u outward; u_c, u_o the wall's inner and outer
        faces. Inside, the cavity's 45-degree lean-in (main_part) meets the cut at the screen."""
        pts = [(u_c - 6.0, T), (u_o - ct, T), (u_o, T - ct), (u_o + 1.0, T - ct), (u_o + 1.0, zt + 2.0),
               (u_c - 6.0, zt + 2.0)]
        return [(u, z + dz) for u, z in pts]

    def cut(to3d, u_c: float, u_o: float, s1: float) -> bd.Part:
        s2 = s1 + c.flush_ramp
        secs = []
        for s, dz in ((-s2, lift), (-s1, 0.0), (s1, 0.0), (s2, lift)):
            secs.append(bd.Face(bd.Wire.make_polygon([to3d(u, s, z) for u, z in profile(u_c, u_o, dz)], close=True)))
        return bd.loft(secs, ruled=True)

    xc, xo = p.W / 2 + f, c.outer_W(p) / 2
    yc, yo = p.L / 2 + f, c.outer_L(p) / 2
    s_side = p.L / 2 - p.corner_r - c.flush_ramp  # flush between the corners, ramps ending where they begin
    s_end = p.W / 2 - p.corner_r - c.flush_ramp
    return [
        cut(lambda u, s, z: bd.Vector(u, s, z), xc, xo, s_side),  # right (+x)
        cut(lambda u, s, z: bd.Vector(-u, s, z), xc, xo, s_side),  # left
        cut(lambda u, s, z: bd.Vector(s, -u, z), yc, yo, s_end),  # bottom (-y)
    ]


def openings(p: Phone, c: Case) -> list[bd.Part]:
    """Buttons and USB-C open to the front (no strip of wall over them); speaker and microphones
    as rounded windows."""
    zc, zt, T = p.T / 2, c.z_front(p), p.T + c.fit_z
    surface = c.wall - 0.2  # from the cutting planes (0.2 outside the cavity) to the outer face
    reach = c.fit + 0.2 + 1.5  # into the cavity, past the lean-in at the wall's top
    z_hi = zt + 2.0
    cuts = []

    def top(xo: float):  # the wall's top across it: flat at the screen, then the outer chamfer
        return lambda u: T - max(0.0, u - (xo - c.top_chamfer))

    # Buttons: one notch over power and volume, from below the buttons out through the front.
    m = c.btn_margin
    y0, y1 = p.from_top(p.vol_top + p.vol_len) - m, p.from_top(p.power_top) + m
    z_lo = zc - c.btn_cut_h / 2
    pl = side_plane((p.W / 2 + c.fit + 0.2, (y0 + y1) / 2, (z_lo + z_hi) / 2), (1, 0, 0), (0, 1, 0))
    notch = lambda w, hh, g: rr(w + 2 * g, hh + 2 * g, c.notch_r + g)  # noqa: E731
    cuts.append(flared_cut(pl, y1 - y0, z_hi - z_lo, reach, surface, c.cut_round, notch))
    xo = c.outer_W(p) / 2
    xa = p.W / 2 + c.fit - 1.5
    cuts += [round_notch_corner(xa, xo, y, top(xo), c.cut_round, s, c.cut_round, dz=-1) for y, s in ((y0, 1), (y1, -1))]

    # USB-C: open to the front too; with the bottom edge at the screen, a strip over the plug
    # would be about 1 mm tall. Built across the +x wall, then turned onto the bottom (-y).
    yo = c.outer_L(p) / 2
    z_lo = zc - c.usb_cut_h / 2
    pl = side_plane((p.L / 2 + c.fit + 0.2, 0.0, (z_lo + z_hi) / 2), (1, 0, 0), (0, 1, 0))
    u_shape = lambda w, hh, g: rr(w + 2 * g, hh + 2 * g, c.usb_cut_h / 2 + g)  # noqa: E731 - round-bottomed U
    usb = [flared_cut(pl, c.usb_cut_w, z_hi - z_lo, reach, surface, c.cut_round, u_shape)]
    xa = p.L / 2 + c.fit - 1.5
    w = c.usb_cut_w / 2
    usb += [round_notch_corner(xa, yo, y, top(yo), c.cut_round, s, c.cut_round, dz=-1) for y, s in ((-w, 1), (w, -1))]
    cuts += [bd.Rot(0, 0, -90) * u for u in usb]  # (x, y) -> (y, -x): the +x wall onto the bottom

    # Speaker and bottom microphone (bottom edge), top microphone.
    def window(x: float, length: float, h: float, bottom: bool = True):
        if bottom:
            pl = side_plane((x, -(p.L / 2 + c.fit + 0.2), zc), (0, -1, 0), (1, 0, 0))
        else:
            pl = side_plane((x, p.L / 2 + c.fit + 0.2, zc), (0, 1, 0), (-1, 0, 0))
        cuts.append(flared_cut(pl, length, h, reach, surface, c.cut_round))

    sx0, sx1 = p.spk_x0 - c.spk_margin, p.spk_x1 + c.spk_margin
    window((sx0 + sx1) / 2, sx1 - sx0, c.spk_cut_h)
    window(p.mic_bot_x, c.mic_cut_w, c.mic_cut_h)
    window(p.mic_top_x, c.mic_cut_w, c.mic_cut_h, bottom=False)
    return cuts


def camera_ring(p: Phone = PHONE, c: Case = CASE) -> bd.Part:
    """The collar round the camera bar, with a flange that sits in the back's recess, inside."""
    cl, ch = collar_size(p, c)
    z_top = c.collar_top(p)
    ring = prism(bd.Pos(0, p.cam_y) * stadium(cl, ch), z_top, 0.0)
    ring = bd.fillet(ring.edges().group_by(bd.Axis.Z)[0], c.collar_fillet)  # the outer top edge
    fw = c.ring_flange
    body = ring + prism(bd.Pos(0, p.cam_y) * stadium(cl + 2 * fw, ch + 2 * fw), -c.ring_flange_t, 0.0)
    # Camera opening, with a 45-degree bevel on the inner top edge (keeps flash glare off the lenses).
    hl, hh = p.cam_len + 2 * c.collar_clear, p.cam_h + 2 * c.collar_clear
    hole = prism(bd.Pos(0, p.cam_y) * stadium(hl, hh), z_top - 1, 1)
    k = c.collar_chamfer
    bevel = ruled(bd.Pos(0, p.cam_y) * stadium(hl, hh), z_top + k,
                  bd.Pos(0, p.cam_y) * stadium(hl + 2 * (k + 0.3), hh + 2 * (k + 0.3)), z_top - 0.3)
    return body - hole - bevel


def back_face(p: Phone = PHONE, c: Case = CASE) -> shapely.Geometry:
    """The streamline layer's region, in phone (x, y): the back's outline where the base chamfer
    crosses the middle of the first layer (where PrusaSlicer slices it, so the brim meets it),
    less the ring's opening."""
    Wo, Lo, b = c.outer_W(p), c.outer_L(p), max(c.base_chamfer - c.stream_h / 2, 0.0)
    cl, ch = collar_size(p, c)
    g = c.ring_clear
    return rr_shp(Wo - 2 * b, Lo - 2 * b, c.outer_corner_r - b).difference(stadium_shp(cl + 2 * g, ch + 2 * g, 0.0, p.cam_y))
