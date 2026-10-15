"""Preview renders and engineering sections for the README."""

from __future__ import annotations

import pathlib

import numpy as np

from .params import Case, Phone
from .phone import phone_parts, phone_solid
from .render import COLORS, add, mesh, plotter, pv, shoot  # render sets up headless OpenGL first
from .sections import section_figure, to_trimesh

UP = (0, 1, 0)


def _phone(pl, parts, dz=0.0, screen=True):
    add(pl, parts["body"].translate((0, 0, dz)), COLORS["hazel"], specular=0.35)
    add(pl, parts["bar"].translate((0, 0, dz)), COLORS["bar"], specular=0.6)
    add(pl, parts["lenses"].translate((0, 0, dz)), COLORS["lens"], specular=0.9)
    add(pl, parts["buttons"].translate((0, 0, dz)), COLORS["hazel"])
    if screen:
        add(pl, parts["screen"].translate((0, 0, dz)), COLORS["screen"], specular=0.8)


def _plate(pl, mp, c: Case, scheme: str, dz=0.0):
    m = mp.translate((0, 0, dz))
    if scheme == "galaxy":
        add(pl, m, COLORS["galaxy"], specular=0.7)
    else:  # two-colour: clear base, galaxy black terraces + collar
        z_cut = -c.plate_t - (c.two_color_level - 0.5) * c.topo_step + dz
        base = m.clip(normal=(0, 0, -1), origin=(0, 0, z_cut), invert=True)
        top = m.clip(normal=(0, 0, -1), origin=(0, 0, z_cut), invert=False)
        add(pl, top, COLORS["galaxy"], specular=0.7)
        add(pl, base, "#b4bfae", opacity=0.6, specular=0.9)  # clear PETG over the Hazel back


def render_all(b, plate_part, p: Phone, c: Case, out: pathlib.Path) -> None:
    mb, mp = mesh(b), mesh(plate_part)
    parts = {k: mesh(v) for k, v in phone_parts(p).items()}
    back_cam = [(-150, -60, -300), (0, -4, -2), UP]
    front_cam = [(160, -50, 300), (0, -4, 5), UP]

    for scheme in ("galaxy", "twotone"):
        pl = plotter()
        _phone(pl, parts, screen=False)
        add(pl, mb, COLORS["tpu"], specular=0.3)
        _plate(pl, mp, c, scheme)
        shoot(pl, str(out / f"back_{scheme}.png"), back_cam, zoom=1.0)

    pl = plotter()
    _phone(pl, parts)
    add(pl, mb, COLORS["tpu"], specular=0.3)
    shoot(pl, str(out / "front.png"), front_cam, zoom=1.0)

    # Camera-end close-up from the back.
    pl = plotter()
    _phone(pl, parts, screen=False)
    add(pl, mb, COLORS["tpu"], specular=0.3)
    _plate(pl, mp, c, "galaxy")
    shoot(pl, str(out / "camera_closeup.png"), [(-90, 0, -160), (5, 52, -2), UP], zoom=0.75, fit=False)

    # Corner close-up from the front (lip, corner bumper, buttons).
    pl = plotter()
    _phone(pl, parts)
    add(pl, mb, COLORS["tpu"], specular=0.3)
    shoot(pl, str(out / "corner_closeup.png"), [(190, 75, 170), (30, 52, 4), UP], zoom=0.55, fit=False)

    # The plate alone, terraces tinted by height (the print itself is one or two colours).
    pl = plotter()
    m = mp.copy()
    h = np.clip(-m.points[:, 2] - c.plate_t, 0, c.topo_levels * c.topo_step)
    m["height"] = h
    pl.add_mesh(m, scalars="height", cmap="gist_earth", clim=(-0.25, c.topo_levels * c.topo_step + 0.1),
                smooth_shading=False, specular=0.2, ambient=0.25, show_scalar_bar=False)
    shoot(pl, str(out / "plate_relief.png"), [(-30, -25, -330), (0, -4, -2), UP], zoom=1.05)

    # Exploded: plate behind, phone in front of the bumper.
    pl = plotter()
    add(pl, mb, COLORS["tpu"], specular=0.3)
    _plate(pl, mp, c, "galaxy", dz=-35)
    _phone(pl, parts, dz=35)
    shoot(pl, str(out / "exploded.png"), [(-300, -200, -120), (0, 0, 0), (0, 0, 1)], zoom=1.1)

    # Print layout on an MK3 bed (250 x 210).
    from .build import to_print_bumper, to_print_plate

    pb = mesh(to_print_bumper(b, p, c)).translate((65, 105, 0))
    pp = mesh(to_print_plate(plate_part)).translate((180, 105, 0))
    pl = plotter()
    bed = pv.Box(bounds=(0, 250, 0, 210, -1.2, 0))
    add(pl, bed, COLORS["bed"], specular=0.1)
    add(pl, pb, COLORS["tpu"], specular=0.3)
    add(pl, pp, COLORS["galaxy"], specular=0.7)
    shoot(pl, str(out / "print_layout.png"), [(125, -160, 300), (125, 105, 0), (0, 0, 1)], zoom=1.05)

    sections(b, plate_part, p, c, out / "sections.png")


def sections(b, plate_part, p: Phone, c: Case, path: pathlib.Path) -> None:
    M = {"phone": to_trimesh(phone_solid(p)), "plate": to_trimesh(plate_part), "bumper": to_trimesh(b)}
    hw, hl = p.W / 2, p.L / 2
    d = np.array([1, 1, 0]) / np.sqrt(2)
    cx, cy = hw - p.corner_r, hl - p.corner_r
    zt = c.z_front(p) + 1
    zb = c.collar_top(p) - 1
    views = [
        dict(name="Long side (y = -40): side lip bevel, grip flute, rim over plate bevel",
             origin=(0, -40, 0), normal=(0, 1, 0), u=(-1, 0, 0), xlim=(33, 41), ylim=(-3, zt)),
        dict(name="Corner (diagonal): 2.4 mm TPU + 1.3 mm air pocket",
             origin=(cx, cy, 0), normal=(d[1], -d[0], 0), u=tuple(d), xlim=(9, 17.5), ylim=(-3, zt)),
        dict(name="Top end through the camera bar (x = 0): collar 1 mm above the bar",
             origin=(0, 0, 0), normal=(1, 0, 0), u=(0, 1, 0), xlim=(40, 84), ylim=(zb, zt)),
        dict(name="Bottom end at USB-C (x = 0)",
             origin=(0, 0, 0), normal=(1, 0, 0), u=(0, -1, 0), xlim=(74, 84), ylim=(-3, zt)),
        dict(name="Right side at the power button",
             origin=(0, p.from_top(p.power_top + p.power_len / 2), 0), normal=(0, 1, 0), u=(1, 0, 0), xlim=(33, 41), ylim=(-3, zt)),
        dict(name="Right side at the volume post (recessed off the rocker)",
             origin=(0, p.from_top(p.vol_top + p.vol_len / 2), 0), normal=(0, 1, 0), u=(1, 0, 0), xlim=(33, 41), ylim=(-3, zt)),
    ]
    section_figure(M, views, str(path), "Cross-sections: phone (green), TPU bumper (dark), PETG plate (blue)")
