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

    # The button side in raking light: the grip texture and the open notch over the buttons.
    pl = plotter()
    pl.add_light(pv.Light(position=(0, 200, 30), focal_point=(39, 0, 3), intensity=0.7, light_type="scene light"))
    _phone(pl, parts)
    add(pl, mb, COLORS["tpu"], specular=0.35)
    _plate(pl, mp, c, "galaxy")
    shoot(pl, str(out / "side_texture.jpg"), [(175, -135, 75), (22, 2, 3), UP], zoom=1.0, fit=False)

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
        dict(name="Long side (y = -40): side lip bevel, grip texture, rim over plate bevel",
             origin=(0, -40, 0), normal=(0, 1, 0), u=(-1, 0, 0), xlim=(33, 41), ylim=(-3, zt)),
        dict(name="Corner (diagonal): 2.4 mm TPU + 1.3 mm air pocket",
             origin=(cx, cy, 0), normal=(d[1], -d[0], 0), u=tuple(d), xlim=(9, 17.5), ylim=(-3, zt)),
        dict(name="Top end through the camera bar (x = 0): collar 1 mm above the bar",
             origin=(0, 0, 0), normal=(1, 0, 0), u=(0, 1, 0), xlim=(40, 84), ylim=(zb, zt)),
        dict(name="Bottom end at USB-C (x = 0)",
             origin=(0, 0, 0), normal=(1, 0, 0), u=(0, -1, 0), xlim=(74, 84), ylim=(-3, zt)),
        dict(name="Right side at the power button",
             origin=(0, p.from_top(p.power_top + p.power_len / 2), 0), normal=(0, 1, 0), u=(1, 0, 0), xlim=(33, 41), ylim=(-3, zt)),
        dict(name="Right side at the volume rocker: open notch",
             origin=(0, p.from_top(p.vol_top + p.vol_len / 2), 0), normal=(0, 1, 0), u=(1, 0, 0), xlim=(33, 41), ylim=(-3, zt)),
    ]
    section_figure(M, views, str(path), "Cross-sections: phone (green), TPU bumper (dark), PETG plate (blue)")




def streamline_previews(lyr, region, bands, p: Phone, c: Case, out: pathlib.Path, flow=None, outer=None,
                        rim: str = "#9aa59a", palettes=None) -> None:
    """Toolpaths and predicted colours of the streamline layer, seen from the back.
    flow = (xs, ys, v, dye) adds the flow figure (vorticity, dye) and the four-step pipeline strip.
    outer: the part's outline round the region (default the phone's), drawn in `rim`."""
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

    plate_shape = outline_shp(p, 0.0) if outer is None else outer
    H = 9.0
    aspect = (p.W + 6) / (p.L + 6)
    lw = (lyr.d_sep + 0.05) * H * 72 / (p.L + 6)  # printed width in points

    def limits(ax):
        ax.set_xlim(-p.W / 2 - 3, p.W / 2 + 3); ax.set_ylim(-p.L / 2 - 3, p.L / 2 + 3)
        ax.set_aspect(1); ax.axis("off")

    def frame(ax, base):
        ax.add_patch(patch(plate_shape, facecolor=rim, edgecolor="none"))  # the rim round the layer
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
    keys = list(PALETTES) if palettes is None else list(palettes)
    fig, axes = plt.subplots(1, len(keys), figsize=(len(keys) * H * aspect + 0.6, H + 0.5))
    for ax, key in zip(np.atleast_1d(axes), keys):
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
              "3. Contour it into toolpaths\n(dithered)", "4. Feed color by hand\n(PETG pieces)"]
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


def fused_renders(walls, back, ring, lyr, bands, p: Phone, c: Case, out: pathlib.Path) -> None:
    """The fused case on the phone. The streamline layer is the back's bed-side face, so it is
    flat: drawn as a coloured skin on the black back. walls: the textured TPU mesh in the phone
    frame."""
    from .toolpath import mix

    mw, mb, mr = mesh(walls), mesh(back), mesh(ring)
    parts = {k: mesh(v) for k, v in phone_parts(p).items()}
    _, _, seq = PALETTES["petg"]
    pieces = [(seq[k % len(seq)][1], mm) for k, (_, _, mm) in enumerate(bands)]
    widths = [lyr.widths(k) for k in range(len(lyr.lines))]
    skin = ridge_mesh(lyr.lines, mix(lyr, pieces), widths, -c.back_t - 0.004, 0.012)

    def scene(screen=False, raking=None):
        pl = plotter()
        if raking:
            pl.add_light(pv.Light(position=raking[0], focal_point=raking[1], intensity=0.8, light_type="scene light"))
        _phone(pl, parts, screen=screen)
        add(pl, mw, COLORS["tpu"], specular=0.3)
        add(pl, mb, COLORS["galaxy"], specular=0.5)
        add(pl, mr, COLORS["galaxy"], specular=0.6)
        pl.add_mesh(skin, scalars="rgb", rgb=True, smooth_shading=True, specular=0.6, specular_power=40, ambient=0.2)
        return pl

    shoot(scene(), str(out / "fused_back.jpg"), [(-150, -60, -300), (0, -4, -2), UP], zoom=1.0)
    shoot(scene(), str(out / "fused_plan.jpg"), [(0, 0, -400), (0, 0, -2), UP], zoom=1.0, parallel=True)
    shoot(scene(screen=True), str(out / "fused_front.jpg"), [(160, -50, 300), (0, -4, 5), UP], zoom=1.0)
    # The bottom corners keep their lip; the bottom and the long sides are flush with the screen.
    shoot(scene(screen=True), str(out / "fused_corner.jpg"), [(-95, -150, 110), (-26, -68, 5), UP], zoom=0.75, fit=False)
    # The palm side (left, seen from the screen) in raking light: the grip and the flush top.
    shoot(scene(screen=True, raking=((0, 200, 30), (-39, 0, 3))), str(out / "fused_side.jpg"),
          [(-175, -135, 75), (-22, 2, 3), UP], zoom=1.0, fit=False)
    shoot(scene(), str(out / "fused_camera.jpg"), [(-90, 0, -160), (5, 52, -2), UP], zoom=0.75, fit=False)

    # Assembly order: the ring drops into the case, then the phone.
    pl = plotter()
    add(pl, mw, COLORS["tpu"], specular=0.3)
    add(pl, mb, COLORS["galaxy"], specular=0.5)
    add(pl, mr.translate((0, 0, 30)), COLORS["galaxy"], specular=0.6)
    _phone(pl, parts, dz=70)
    shoot(pl, str(out / "fused_exploded.jpg"), [(-330, -260, 150), (0, 10, 32), (0, 0, 1)], zoom=1.05)



def print_sequence(gcode: pathlib.Path, lyr, bands, to_bed, z_tpu: float, path: pathlib.Path) -> None:
    """The main part's print in four layers, drawn from its G-code: the brim and the hand-fed
    streamline layer (predicted colours), the black back's top (ironed), the first TPU layer,
    and the lips."""
    import re

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    from .toolpath import mix

    segs: dict[float, list] = {}
    z, typ, x, y = 0.0, "", 0.0, 0.0
    for s in gcode.read_text(errors="ignore").splitlines():
        if s.startswith(";Z:"):
            z = round(float(s[3:]), 3)
        elif s.startswith(";TYPE:"):
            typ = s[6:]
        elif s.startswith(";STREAMLINE_LAYER_START"):
            typ = "streamline"
        elif s.startswith("G1"):
            d = dict(re.findall(r"\b([XYE])(-?[\d.]+)", s.split(";")[0]))
            nx, ny = float(d.get("X", x)), float(d.get("Y", y))
            if "E" in d and float(d["E"]) > 0 and (nx, ny) != (x, y) and typ != "streamline":
                segs.setdefault(z, []).append(((x, y), (nx, ny), typ))
            x, y = nx, ny
    zs = sorted(segs)
    z1 = min(q for q in zs if q > 0.01)  # the purge line before it carries no ;Z: marker
    z_iron = max(q for q in zs if q <= z_tpu + 1e-6)
    z_t = min(q for q in zs if q > z_tpu)
    z_lip = zs[-3]
    _, _, seq = PALETTES["petg"]
    cols = mix(lyr, [(seq[k % len(seq)][1], mm) for k, (_, _, mm) in enumerate(bands)])
    fig, axes = plt.subplots(1, 4, figsize=(15, 8.6))
    black, tpu, bed = "#23252e", "#6f757e", "#e4e2dc"
    pt_mm = 0.98 * 3.6 * 72 / 94  # points per mm at this panel size
    titles = [f"1. Layer 1 ({lyr.h:g} mm): black brim, then the\nstreamline layer, fed by hand",
              f"2. Top of the black PETG back\n(z {z_iron:g} mm, ironed)",
              f"3. First TPU layer (z {z_t:g} mm):\nhot, fan off, for the bond",
              f"4. The lips (z {z_lip:g} mm): top edge\nand corners; the rest is flush"]
    for k, (ax, title) in enumerate(zip(axes, titles)):
        zz = [z1, z_iron, z_t, z_lip][k]
        lines = segs.get(zz, [])
        if k == 0:
            brim = [(a, b) for a, b, t in lines if t.startswith("Skirt")]
            ax.add_collection(LineCollection(brim, lw=0.62 * pt_mm, color=black))
            pts = [to_bed(l) for l in lyr.lines]
            rgb = [0.5 * (cl[:-1] + cl[1:]) for cl in cols]
            ax.add_collection(LineCollection([sg for q in pts for sg in np.stack([q[:-1], q[1:]], 1)],
                                             colors=np.vstack(rgb), lw=0.6 * pt_mm))
        else:
            col = black if zz <= z_tpu + 1e-6 else tpu
            ax.add_collection(LineCollection([(a, b) for a, b, t in lines if t != "Ironing"], lw=0.62 * pt_mm, color=col))
            iron = [(a, b) for a, b, t in lines if t == "Ironing"]
            if iron:  # every fourth ironing pass, or they merge into grey
                ax.add_collection(LineCollection(iron[::4], lw=0.25, color="#9aa3b5", alpha=0.8))
        ax.set_facecolor("#8d8a83" if k == 0 else bed)  # a mid-grey bed under white and black beads
        ax.set_xlim(78, 172); ax.set_ylim(14, 196); ax.set_aspect(1)
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(title, fontsize=10)
    fig.subplots_adjust(0.01, 0.01, 0.99, 0.9, wspace=0.04)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fused_sections(walls, back, ring, p: Phone, c: Case, path: pathlib.Path) -> None:
    from .sections import STYLE

    STYLE.setdefault("ring", ("#24476b", 0.95))
    M = {"phone": to_trimesh(phone_solid(p)), "plate": to_trimesh(back), "bumper": walls, "ring": to_trimesh(ring)}
    hw, hl = p.W / 2, p.L / 2
    d = np.array([1, 1, 0]) / np.sqrt(2)
    cx, cy = -(hw - p.corner_r), -(hl - p.corner_r)
    zt = c.z_front(p) + 1
    views = [
        dict(name="Left side (y = -30): flush with the screen, 45-degree lean-in",
             origin=(0, -30, 0), normal=(0, 1, 0), u=(-1, 0, 0), xlim=(33, 41), ylim=(-2, zt)),
        dict(name="Left side (y = 66): the ramp up to the corner lip",
             origin=(0, 66, 0), normal=(0, 1, 0), u=(-1, 0, 0), xlim=(33, 41), ylim=(-2, zt)),
        dict(name="Bottom-left corner (diagonal): lip, corner pocket",
             origin=(cx, cy, 0), normal=(d[1], -d[0], 0), u=tuple(-d), xlim=(9, 17.5), ylim=(-2, zt)),
        dict(name="Top end through the camera ring (x = 0)",
             origin=(0, 0, 0), normal=(1, 0, 0), u=(0, 1, 0), xlim=(40, 84), ylim=(c.collar_top(p) - 1, zt)),
        dict(name="Bottom end at USB-C (x = 0): notch open to the front",
             origin=(0, 0, 0), normal=(1, 0, 0), u=(0, -1, 0), xlim=(74, 84), ylim=(-2, zt)),
        dict(name="Right side at the volume rocker: notch open to the front",
             origin=(0, p.from_top(p.vol_top + p.vol_len / 2), 0), normal=(0, 1, 0), u=(1, 0, 0), xlim=(33, 41), ylim=(-2, zt)),
    ]
    section_figure(M, views, str(path), "Cross-sections: phone (green), TPU walls (dark), PETG back (blue), camera ring (navy)")


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
