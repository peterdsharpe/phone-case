"""TPU bumper: side walls, front lip, corner cushions, and the rear rim that holds the back plate.

Printed face-down (front lip on the bed), so the lip needs no support and its
height can be uniform while the long sides bevel down for edge-swipe gestures.
"""

from __future__ import annotations

import build123d as bd

from .geom import flared_cut, outline, prism, rr, ruled, side_plane, stadium
from .params import CASE, PHONE, Case, Phone
from .plate import collar_size, plate_blank


def bumper(p: Phone = PHONE, c: Case = CASE) -> bd.Part:
    Wo, Lo = c.outer_W(p), c.outer_L(p)
    zb, zf = c.z_back, c.z_front(p)
    f = c.fit

    # Outer shell -------------------------------------------------------------------
    body = prism(rr(Wo, Lo, c.outer_corner_r), zb, zf)
    body = bd.chamfer(body.edges().group_by(bd.Axis.Z)[-1], c.front_chamfer)
    body = bd.fillet(body.edges().group_by(bd.Axis.Z)[0], c.back_fillet)

    # Phone cavity, hugging the rounded front edge so the lip pulls the phone down.
    cav = prism(outline(p, -f), 0.0, p.T + c.fit_z)
    cav = bd.fillet(cav.edges().group_by(bd.Axis.Z)[-1], p.edge_r + f)
    # Corner air pockets: a tighter corner radius in the middle of the wall leaves
    # a ~1.3 mm gap at each phone corner, so a corner hit squashes TPU before glass.
    relief = prism(outline(p, -f, corner_r=c.corner_relief_r + f), c.corner_relief_margin, p.T - c.corner_relief_margin)

    # Front lip opening: straight throat, then bevels (45 deg on the long sides).
    h_in = c.lip_side_inner_h
    r_lip = p.corner_r - (c.lip_side + c.lip_end) / 2
    w0, l0 = p.W - 2 * c.lip_side, p.L - 2 * c.lip_end
    throat = prism(rr(w0, l0, r_lip), p.T - 1.0, p.T + h_in)
    rise = c.lip_h - h_in
    dz = rise + 0.4  # overshoot the front face
    gs, ge = dz, c.lip_end_bevel * dz / rise
    bevel = ruled(rr(w0, l0, r_lip), p.T + h_in, rr(w0 + 2 * gs, l0 + 2 * ge, r_lip + (gs + ge) / 2), p.T + h_in + dz)

    # Back: pocket for the plate (+gap) and the window through the rim.
    pocket = plate_blank(p, c, grow=c.plate_gap)
    cl, ch = collar_size(p, c)
    window_sk = outline(p, c.flange_reach) + bd.Pos(0, p.cam_y) * stadium(cl + 0.6, ch + 0.6)
    window = prism(window_sk, zb - 1.0, -c.plate_t)

    cutters = [cav, relief, throat, bevel, pocket, window, *side_openings(p, c)]
    if c.grip:
        cutters.append(grip_flutes(p, c))
    for cut in cutters:
        body = body - cut
    return body


def side_openings(p: Phone, c: Case) -> list[bd.Part]:
    """Openings for buttons, USB-C, speaker and microphones."""
    Wo, Lo = c.outer_W(p), c.outer_L(p)
    zc = p.T / 2
    cuts = []
    depth_in = c.fit + 0.6  # start inside the cavity
    depth_out = c.wall + 0.4

    # Right side (+x): power, then volume split in two by a post.
    def right(y0: float, y1: float, h: float):
        pl = side_plane((p.W / 2 + c.fit + 0.2, (y0 + y1) / 2, zc), (1, 0, 0), (0, 1, 0))
        cuts.append(flared_cut(pl, y1 - y0, h, depth_in + 0.2, depth_out - 0.2, c.cut_flare))

    m = c.btn_margin
    right(p.from_top(p.power_top + p.power_len) - m, p.from_top(p.power_top) + m, c.btn_cut_h)
    v_hi = p.from_top(p.vol_top) + m
    v_lo = p.from_top(p.vol_top + p.vol_len) - m
    v_mid = (v_hi + v_lo) / 2
    if c.vol_post > 0:
        right(v_mid + c.vol_post / 2, v_hi, c.btn_cut_h)
        right(v_lo, v_mid - c.vol_post / 2, c.btn_cut_h)
        # The rocker is one piece: recess the post's inner face so it never presses it.
        depth = p.btn_proud + 0.2
        y0, y1 = p.from_top(p.vol_top + p.vol_len) - 0.5, p.from_top(p.vol_top) + 0.5
        cuts.append(bd.Pos(p.W / 2 + depth / 2 - 0.25, (y0 + y1) / 2, zc) * bd.Box(depth + 0.5, y1 - y0, p.btn_h + 1.0))
    else:
        right(v_lo, v_hi, c.btn_cut_h)

    # Bottom (-y): speaker, USB-C, microphone.
    def bottom(x: float, length: float, h: float):
        pl = side_plane((x, -(p.L / 2 + c.fit + 0.2), zc), (0, -1, 0), (1, 0, 0))
        cuts.append(flared_cut(pl, length, h, depth_in + 0.2, depth_out - 0.2, c.cut_flare))

    bottom(0.0, c.usb_cut_w, c.usb_cut_h)
    sx0, sx1 = p.spk_x0 - c.spk_margin, p.spk_x1 + c.spk_margin
    bottom((sx0 + sx1) / 2, sx1 - sx0, c.spk_cut_h)
    bottom(p.mic_bot_x, c.mic_cut_w, c.mic_cut_h)

    # Top (+y): microphone.
    pl = side_plane((p.mic_top_x, p.L / 2 + c.fit + 0.2, zc), (0, 1, 0), (-1, 0, 0))
    cuts.append(flared_cut(pl, c.mic_cut_w, c.mic_cut_h, depth_in + 0.2, depth_out - 0.2, c.cut_flare))
    return cuts


def grip_flutes(p: Phone, c: Case) -> bd.Part:
    """Shallow vertical flutes on both long sides (vertical in the print, so they print cleanly)."""
    Wo = c.outer_W(p)
    z0 = c.z_back + c.back_fillet + 0.3
    z1 = c.z_front(p) - c.front_chamfer - 0.3
    xoff = Wo / 2 + c.grip_r - c.grip_depth
    rods = []
    for sign, (ya, yb) in ((-1, c.grip_left_y), (+1, c.grip_right_y)):
        n = int((yb - ya) // c.grip_pitch) + 1
        y0 = (ya + yb) / 2 - (n - 1) * c.grip_pitch / 2
        for i in range(n):
            rods.append(bd.Pos(sign * xoff, y0 + i * c.grip_pitch, z0) * bd.Cylinder(c.grip_r, z1 - z0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)))
    out = rods[0]
    for r in rods[1:]:
        out = out + r
    return out
