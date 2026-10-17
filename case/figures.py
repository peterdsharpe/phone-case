"""Preview renders and engineering sections for the README."""

from __future__ import annotations

import pathlib

import numpy as np

from .params import Case, Phone
from .phone import phone_parts, phone_solid
from .render import COLORS, add, mesh, plotter, pv, shoot  # render sets up headless OpenGL first
from .sections import section_figure, to_trimesh
from .toolpath import PALETTES

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
        z_cut = -c.plate_t - (c.two_color_level - 0.5) * c.plate_layer + dz
        base = m.clip(normal=(0, 0, -1), origin=(0, 0, z_cut), invert=True)
        top = m.clip(normal=(0, 0, -1), origin=(0, 0, z_cut), invert=False)
        add(pl, top, COLORS["galaxy"], specular=0.7)
        add(pl, base, "#b4bfae", opacity=0.6, specular=0.9)  # clear PETG over the Hazel back


def render_all(b, plate_part, p: Phone, c: Case, out: pathlib.Path) -> None:
    mb, mp = mesh(b), mesh(plate_part)
    parts = {k: mesh(v) for k, v in phone_parts(p).items()}
    back_cam = [(-150, -60, -300), (0, -4, -2), UP]
    front_cam = [(160, -50, 300), (0, -4, 5), UP]

    relief = c.design in ("topo", "karman")
    for scheme in ("galaxy", "twotone") if relief else ("galaxy",):
        pl = plotter()
        _phone(pl, parts, screen=False)
        add(pl, mb, COLORS["tpu"], specular=0.3)
        _plate(pl, mp, c, scheme)
        shoot(pl, str(out / f"back_{scheme}.jpg"), back_cam, zoom=1.0)

    pl = plotter()
    _phone(pl, parts)
    add(pl, mb, COLORS["tpu"], specular=0.3)
    shoot(pl, str(out / "front.jpg"), front_cam, zoom=1.0)

    # Camera-end close-up from the back.
    pl = plotter()
    _phone(pl, parts, screen=False)
    add(pl, mb, COLORS["tpu"], specular=0.3)
    _plate(pl, mp, c, "galaxy")
    shoot(pl, str(out / "camera_closeup.jpg"), [(-90, 0, -160), (5, 52, -2), UP], zoom=0.75, fit=False)

    # Corner close-up from the front (lip, corner bumper, buttons).
    pl = plotter()
    _phone(pl, parts)
    add(pl, mb, COLORS["tpu"], specular=0.3)
    shoot(pl, str(out / "corner_closeup.jpg"), [(190, 75, 170), (30, 52, 4), UP], zoom=0.55, fit=False)

    if relief:  # the plate alone, relief tinted by height (the print itself is one or two colours)
        _relief_tint(plotter(), mp, c, out)
    _exploded_and_layout(b, mb, mp, plate_part, parts, p, c, out)  # exploded view, bed layout, sections


def _relief_tint(pl, mp, c: Case, out: pathlib.Path) -> None:
    m = mp.copy()
    hmax = c.topo_levels * c.topo_step if c.design == "topo" else c.flow_ridge_h + c.flow_cyl_h
    h = np.clip(-m.points[:, 2] - c.plate_t, 0, hmax)
    m["height"] = h
    pl.add_mesh(m, scalars="height", cmap="gist_earth", clim=(-0.25 * hmax, hmax * 1.1),
                smooth_shading=False, specular=0.2, ambient=0.25, show_scalar_bar=False)
    shoot(pl, str(out / "plate_relief.jpg"), [(-30, -25, -330), (0, -4, -2), UP], zoom=1.05)


def _exploded_and_layout(b, mb, mp, plate_part, parts, p: Phone, c: Case, out: pathlib.Path) -> None:
    pl = plotter()
    add(pl, mb, COLORS["tpu"], specular=0.3)
    _plate(pl, mp, c, "galaxy", dz=-35)
    _phone(pl, parts, dz=35)
    shoot(pl, str(out / "exploded.jpg"), [(-300, -200, -120), (0, 0, 0), (0, 0, 1)], zoom=1.1)

    # Print layout on an MK3 bed (250 x 210).
    from .build import to_print_bumper, to_print_plate

    pb = mesh(to_print_bumper(b, p, c)).translate((65, 105, 0))
    pp = mesh(to_print_plate(plate_part)).translate((180, 105, 0))
    pl = plotter()
    bed = pv.Box(bounds=(0, 250, 0, 210, -1.2, 0))
    add(pl, bed, COLORS["bed"], specular=0.1)
    add(pl, pb, COLORS["tpu"], specular=0.3)
    add(pl, pp, COLORS["galaxy"], specular=0.7)
    shoot(pl, str(out / "print_layout.jpg"), [(125, -160, 300), (125, 105, 0), (0, 0, 1)], zoom=1.05)

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




def streamline_previews(lyr, region, bands, p: Phone, c: Case, out: pathlib.Path, flow=None) -> None:
    """Toolpaths and predicted colours of the streamline layer, seen from the back.
    flow = (xs, ys, v, dye) adds the flow figure (vorticity, dye) and the four-step pipeline strip."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath

    from .geom import outline_shp
    from .toolpath import mix

    def flip(a):
        return np.c_[-a[:, 0], a[:, 1]]

    def patch(geom, **kw):
        polys = getattr(geom, "geoms", [geom])
        verts, codes = [], []
        for g in polys:
            for ring in [g.exterior, *g.interiors]:
                xy = flip(np.asarray(ring.coords))
                verts += list(xy); codes += [MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY]
        return PathPatch(MPath(verts, codes), **kw)

    plate_shape = outline_shp(p, 0.0)
    H = 9.0
    aspect = (p.W + 6) / (p.L + 6)
    lw = (lyr.d_sep + 0.05) * H * 72 / (p.L + 6)  # printed width in points

    def limits(ax):
        ax.set_xlim(-p.W / 2 - 3, p.W / 2 + 3); ax.set_ylim(-p.L / 2 - 3, p.L / 2 + 3)
        ax.set_aspect(1); ax.axis("off")

    def frame(ax, base):
        ax.add_patch(patch(plate_shape, facecolor="#9aa59a", edgecolor="none"))  # TPU rim (Hazel-ish grey)
        ax.add_patch(patch(region, facecolor=base, edgecolor="none"))
        limits(ax)

    def draw_toolpaths(ax, scale=1.0):
        frame(ax, "#f4f1ea")
        ax.add_collection(LineCollection([flip(l) for l in lyr.lines], lw=lw * 0.35 * scale, color="#1c1d24"))

    def draw_colors(ax, key, scale=1.0):
        title, base, seq = PALETTES[key]
        pieces = [(seq[k % len(seq)][1], mm) for k, (_, _, mm) in enumerate(bands)]
        cols = mix(lyr, pieces)
        frame(ax, base)
        segs, rgb, lws = [], [], []
        for k, (l, cl) in enumerate(zip(lyr.lines, cols)):
            fl = flip(l)
            w = lyr.widths(k)
            segs += list(np.stack([fl[:-1], fl[1:]], 1)); rgb += list(0.5 * (cl[:-1] + cl[1:]))
            lws += list(0.5 * (w[1:] + w[:-1]) * lw * scale / lyr.d_sep)  # printed width
        ax.add_collection(LineCollection(segs, linewidths=lws, colors=rgb, capstyle="round", antialiaseds=False))
        return title

    # 1. toolpaths
    fig, ax = plt.subplots(figsize=(H * aspect, H))
    draw_toolpaths(ax)
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(out / "streamline_toolpaths.png", dpi=200)
    plt.close(fig)

    # 2. predicted colours, one panel per palette
    fig, axes = plt.subplots(1, len(PALETTES), figsize=(len(PALETTES) * H * aspect + 0.6, H + 0.5))
    for ax, key in zip(np.atleast_1d(axes), PALETTES):
        ax.set_title(draw_colors(ax, key), fontsize=9)
    fig.subplots_adjust(0.01, 0.0, 0.99, 0.96, wspace=0.04)
    fig.savefig(out / "streamline_colors.png", dpi=170)
    plt.close(fig)

    if flow is None:
        return
    xs, ys, v, dye = flow
    v = np.asarray(v, float)
    dye = None if dye is None else np.asarray(dye, float)
    if ys[0] > ys[-1]:
        ys, v = ys[::-1], v[:, :, ::-1]
        dye = None if dye is None else dye[:, ::-1]
    w = np.gradient(v[1], xs, axis=0) - np.gradient(v[0], ys, axis=1)
    lim = np.percentile(np.abs(w), 99.5)
    ext = (-xs[-1], -xs[0], ys[0], ys[-1])

    def outside(ax):  # grey over the parts of the flow that are not printed
        ax.add_patch(patch(plate_shape.difference(region), facecolor="#d8d8d8", edgecolor="none", alpha=0.85))
        limits(ax)

    def draw_vorticity(ax, paths=True):
        ax.imshow(w[::-1].T, origin="lower", extent=ext, cmap="RdBu_r", vmin=-lim, vmax=lim, interpolation="bilinear")
        if paths:
            ax.add_collection(LineCollection([flip(l) for l in lyr.lines], lw=0.25, color="#202020", alpha=0.6))
        outside(ax)

    def draw_dye(ax):  # 3 mm stripes of the smoothed inlet label: the streaklines the toolpaths follow
        ax.imshow(np.sin(2 * np.pi * dye / 3.0)[::-1].T, origin="lower", extent=ext, cmap="gray",
                  interpolation="antialiased")
        outside(ax)

    # 3. the flow: vorticity with the toolpaths over it, and the dye label as stripes
    n = 1 if dye is None else 2
    fig, axes = plt.subplots(1, n, figsize=(n * H * aspect, H))
    axes = np.atleast_1d(axes)
    draw_vorticity(axes[0])
    if dye is not None:
        draw_dye(axes[1])
    fig.subplots_adjust(0, 0, 1, 1, wspace=0.02)
    fig.savefig(out / "streamline_flow.png", dpi=200)
    plt.close(fig)

    # 4. the pipeline in one strip: flow -> dye -> toolpaths -> colour
    if dye is None:
        return
    h = 6.0
    fig, axes = plt.subplots(1, 4, figsize=(4 * h * aspect + 0.6, h + 0.55))
    draw_vorticity(axes[0], paths=False)
    draw_dye(axes[1])
    draw_toolpaths(axes[2], scale=h / H)
    draw_colors(axes[3], "petg", scale=h / H)
    titles = ["1. Simulate the wake\n(vorticity)", "2. Follow the dye\n(streaklines)",
              "3. Contour it into toolpaths\n(dithered)", "4. Feed colour by hand\n(PETG pieces)"]
    for ax, t in zip(axes, titles):
        ax.set_title(t, fontsize=11)
    fig.subplots_adjust(0.005, 0.0, 0.995, 0.9, wspace=0.05)
    fig.savefig(out / "streamline_pipeline.png", dpi=150)
    plt.close(fig)


def ridge_mesh(lines, colors, widths, z_face: float, h: float, n_cross: int = 7, up: float = -1.0) -> pv.PolyData:
    """Each toolpath as a printed bead: width per point, height h, standing off the plane
    z = z_face in direction `up`, coloured per point (rgb in 0..1)."""
    s = np.linspace(-1, 1, n_cross)
    hgt = h * np.sqrt(np.clip(1 - s ** 2, 0, 1)) ** 0.6  # flattish top, like a squashed bead
    verts, faces, rgb, base = [], [], [], 0
    for line, col, w in zip(lines, colors, widths):
        n = len(line)
        if n < 2:
            continue
        d = np.gradient(line, axis=0)
        d /= np.maximum(np.hypot(*d.T), 1e-12)[:, None]
        nrm = np.c_[-d[:, 1], d[:, 0]]
        P = line[:, None, :] + nrm[:, None, :] * (s[None, :] * w[:, None] / 2)[..., None]
        Z = z_face + up * np.broadcast_to(hgt, (n, n_cross))
        verts.append(np.concatenate([P, Z[..., None]], axis=2).reshape(-1, 3))
        i, j = np.meshgrid(np.arange(n - 1), np.arange(n_cross - 1), indexing="ij")
        a = (base + i * n_cross + j).ravel()
        faces.append(np.stack([np.full(a.size, 4), a, a + n_cross, a + n_cross + 1, a + 1], 1).ravel())
        rgb.append(np.repeat(col, n_cross, axis=0))
        base += n * n_cross
    m = pv.PolyData(np.vstack(verts), np.concatenate(faces))
    m["rgb"] = (np.clip(np.vstack(rgb), 0, 1) * 255).astype(np.uint8)
    return m


def streamline_renders(lyr, bands, b, plate_part, p: Phone, c: Case, out: pathlib.Path) -> None:
    """The case on the phone with the streamline layer as real beads, for each palette."""
    from .toolpath import mix

    mb, mp = mesh(b), mesh(plate_part)
    parts = {k: mesh(v) for k, v in phone_parts(p).items()}
    widths = [lyr.widths(k) for k in range(len(lyr.lines))]
    ridges = {}
    for key, (_, base, seq) in PALETTES.items():
        pieces = [(seq[k % len(seq)][1], mm) for k, (_, _, mm) in enumerate(bands)]
        ridges[key] = (base, ridge_mesh(lyr.lines, mix(lyr, pieces), widths, -c.plate_t, lyr.h))

    def scene(key, raking=False, size=(1600, 1200)):
        base, rm = ridges[key]
        pl = plotter(size)
        if raking:  # low sun from the side, to show the bead texture
            pl.add_light(pv.Light(position=(-120, 160, -25), focal_point=(0, 0, -1.5), intensity=0.9, light_type="scene light"))
        _phone(pl, parts, screen=False)
        add(pl, mb, COLORS["tpu"], specular=0.3)
        add(pl, mp, base, specular=0.5)
        pl.add_mesh(rm, scalars="rgb", rgb=True, smooth_shading=True, specular=0.55, specular_power=30, ambient=0.2)
        return pl

    back = [(-150, -60, -300), (0, -4, -2), UP]
    for key in PALETTES:
        shoot(scene(key), str(out / f"stream_back_{key}.jpg"), back, zoom=1.0)
    shoot(scene("petg"), str(out / "stream_plan_petg.jpg"), [(0, 0, -400), (0, 0, -2), UP], zoom=1.0, parallel=True)
    # close-ups: the flow parting around the collar, and the wake in raking light
    shoot(scene("petg", raking=True), str(out / "stream_collar_closeup.jpg"),
          [(-110, -10, -210), (0, 45, -2), UP], zoom=1.0, fit=False)
    shoot(scene("petg", raking=True), str(out / "stream_wake_closeup.jpg"),
          [(-88, -133, -109), (5, -40, -2), UP], zoom=1.0, fit=False)
    shoot(scene("petg", raking=True), str(out / "stream_bead_detail.jpg"),
          [(-75, -95, -70), (5, -35, -2), UP], zoom=1.0, fit=False)


def flow_spectra(r: dict, path: pathlib.Path) -> None:
    """Evidence for the spectral check: enstrophy and divergence spectra at lattice resolution
    and the high-pass vorticity residual of the stored field (where grid-scale noise lives)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.ndimage import gaussian_filter

    from .spectra import describe, fields, from_snapshot

    m = from_snapshot(r)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    k = m["k"]
    for name, S, col in (("vorticity (enstrophy)", m["Z"], "#1f77b4"), ("divergence", m["D"], "#ff7f0e")):
        axes[0].loglog(k[1:], S[1:] / m["Z"][1:].max(), color=col, label=name)
    kr = np.array([0.08, 1.0]) * k[-1]
    axes[0].loglog(kr, (kr / kr[0]) ** -3 * 0.5, "k--", lw=0.8, label="k$^{-3}$ (2-D enstrophy cascade)")
    axes[0].axvline(k[-1], color="r", lw=0.8, label="Nyquist")
    axes[0].set_xlabel("k (rad/mm)")
    axes[0].set_title(f"shell spectra ({m['source']} resolution)", fontsize=10)
    axes[0].legend(fontsize=8)
    axes[0].text(0.02, 0.02, describe(m).replace(", ", "\n"), transform=axes[0].transAxes, fontsize=7)
    xs, ys = r["xs"].astype(float), r["ys"].astype(float)
    v = r["shots"][0].astype(float) / float(r["U"])
    if ys[0] > ys[-1]:
        ys, v = ys[::-1], v[:, :, ::-1]
    om, _ = fields(v[0], v[1], xs[1] - xs[0])
    hp = om - gaussian_filter(om, 1.0)
    below = ys < 38.0  # colour scale from the open wake, not the collar's wall layer
    lim = max(np.percentile(np.abs(hp[:, below]), 99.9), 1e-9)
    axes[1].imshow(hp[::-1].T, origin="lower", cmap="RdBu_r", vmin=-lim, vmax=lim, extent=(-xs[-1], -xs[0], ys[0], ys[-1]))
    axes[1].set_title("high-pass vorticity residual of the stored field (seen from the back)", fontsize=10)
    axes[1].set_aspect(1)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
