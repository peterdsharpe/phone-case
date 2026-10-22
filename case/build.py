"""Build every output.  Usage:  uv run python -m case.build [--no-slice] [--no-render]

Writes out/print (STL + PrusaSlicer projects), out/cad (STEP), out/profiles (.ini),
out/renders (PNG), and out/REPORT.md (sizes, masses, print times).
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import tempfile
import time

import build123d as bd
import numpy as np
import shapely
import trimesh

from . import slicer, topo
from .bumper import bumper
from .geom import outline_shp, stadium_shp
from .params import CASE, PHONE, Case, Phone
from .phone import phone_solid
from .plate import collar_size, plate
from .profiles import BUMPER, DENSITY, OUT, PETG, PETG_BUMPER, PLA, RING, ROOT, TPU  # noqa: F401


def relief(p: Phone, c: Case):
    """Relief layers [(geometry, height), ...] for the chosen design, and the region they fill."""
    if c.design == "none":
        return None, None
    cl, ch = collar_size(p, c)
    collar_keepout = stadium_shp(cl + 2 * c.relief_collar_margin, ch + 2 * c.relief_collar_margin, 0, p.cam_y)
    region = outline_shp(p, c.flange_reach + c.relief_margin).difference(collar_keepout)
    if c.design == "streamlines":  # flat plate; the pattern is a toolpath layer added to the G-code
        return None, region
    if c.design == "topo":
        levels = topo.terraces(c.topo_source, region, c.topo_levels, c.min_feature)
        return [(g, c.topo_step) for g in levels], region
    if c.design == "karman":
        from . import flow

        top_strip = region.intersection(shapely.box(-50, p.cam_y, 50, 100))
        dye, cyl = flow.relief(region, width=c.flow_ridge_w, min_feature=c.min_feature, top_strip=top_strip)
        return [(dye.union(cyl), c.flow_ridge_h), (cyl, c.flow_cyl_h)], region
    raise ValueError(f"unknown design {c.design!r}")


def to_print_bumper(part, p: Phone, c: Case):
    """Lip on the bed: rotate 180 deg about y, front face to z = 0 (a build123d part or a trimesh)."""
    if isinstance(part, trimesh.Trimesh):
        m = part.copy()
        m.apply_transform([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, -1, c.z_front(p)], [0, 0, 0, 1]])
        return m
    return bd.Pos(0, 0, c.z_front(p)) * (bd.Rot(0, 180, 0) * part)


def print_mesh(b: bd.Part, p: Phone, c: Case) -> trimesh.Trimesh:
    """The bumper as printed: the CAD tessellated like the STL export, plus the grip texture."""
    with tempfile.TemporaryDirectory() as d:
        bd.export_stl(b, f"{d}/b.stl", tolerance=0.01, angular_tolerance=0.1)
        m = trimesh.load(f"{d}/b.stl")
    if c.grip and c.grip_style == "flow":
        from . import texture

        m = texture.apply(m, p, c)
    return m


def to_print_plate(part: bd.Part) -> bd.Part:
    """Inner face on the bed."""
    return bd.Rot(0, 180, 0) * part


def box_above(z: float, big: float = 400) -> bd.Part:
    return bd.Pos(0, 0, z + big / 2) * bd.Box(big, big, big)


def box_north_of(y: float, big: float = 400) -> bd.Part:
    return bd.Pos(0, y + big / 2, 0) * bd.Box(big, big, big)


def stl(part, path: pathlib.Path):
    if isinstance(part, trimesh.Trimesh):
        part.export(str(path))
    else:
        bd.export_stl(part, str(path), tolerance=0.01, angular_tolerance=0.1)


def mass_g(part, material: str) -> float:
    return part.volume / 1000 * DENSITY[material]


def size(part) -> tuple[float, float, float]:
    if isinstance(part, trimesh.Trimesh):
        return tuple(part.extents)
    bb = part.bounding_box()
    return bb.size.X, bb.size.Y, bb.size.Z


def make_project(stl_path: pathlib.Path, spec: dict, name: str, events=None, ranges=None) -> dict[str, str]:
    """PrusaSlicer project (.3mf with settings) next to the STL; slice it to verify; return stats."""
    cfg = slicer.config(spec["print"], spec["filament"], spec["overrides"])
    ini = OUT / "profiles" / f"{name}.ini"
    slicer.write_ini(cfg, ini, header=f"PrusaSlicer config for {name}: {slicer.PRINTER} + {spec['print']} + {spec['filament']} + overrides.\nImport with File > Import > Import Config.")
    proj = stl_path.with_suffix(".3mf").with_name(f"{name}.3mf")
    proj.unlink(missing_ok=True)
    log = slicer.run(["--load", str(ini), "--center", "125,105", "--export-3mf", "-o", str(proj), str(stl_path)])
    if not proj.exists():
        raise RuntimeError(f"PrusaSlicer wrote no project for {name}:\n{log}")
    slicer.embed_config(proj, cfg)
    if events:
        slicer.add_custom_gcode(proj, events)
    if ranges:
        slicer.add_layer_ranges(proj, ranges)
    gdir = OUT / "gcode"
    gdir.mkdir(exist_ok=True)
    gcode = gdir / f"{name}.gcode"
    gcode.unlink(missing_ok=True)
    log = slicer.run(["--export-gcode", "-o", str(gcode), str(proj)])  # slice the project itself
    if not gcode.exists():  # PrusaSlicer exits 0 even when it refuses to slice
        raise RuntimeError(f"PrusaSlicer wrote no G-code for {name}:\n{log}")
    stats = slicer.gcode_stats(gcode)
    text = gcode.read_text(errors="ignore")
    stats["M600"] = str(sum(1 for line in text.splitlines() if line.startswith("M600")))
    stats["M601"] = str(sum(1 for line in text.splitlines() if line.startswith("M601")))
    return stats


def streamline_plate(p: Phone, c: Case, region, spec: dict, note, tag: str = "petg"):
    """Slice the flat plate, then splice in the streamline layer (see case/toolpath.py).
    Returns the slicer stats, the report section, the layer and its colour bands."""
    from . import spectra, streamplate, toolpath
    from .streamflow import snapshot

    health = spectra.from_snapshot(snapshot(p, c, c.stream_phase))
    note(f"flow snapshot spectral check ({health['source']} resolution): {spectra.describe(health)}")
    if not spectra.healthy(health):
        raise RuntimeError("the flow snapshot fails the spectral check (grid-scale instability): "
                           f"{spectra.describe(health)}. Pick another Case.stream_phase or fix the solver.")
    spec = dict(spec, overrides=dict(spec["overrides"], first_layer_height=c.base_layer,
                                     max_layer_height=max(0.40, c.stream_h)))  # the slot for the streamline layer
    n_base = round(c.plate_t / c.base_layer)
    assert abs(n_base * c.base_layer - c.plate_t) < 1e-6, "plate_t must be a whole number of base layers"
    z_top = round(c.plate_t + c.stream_h, 4)
    ranges = [(c.base_layer, c.plate_t, c.base_layer), (c.plate_t, z_top, c.stream_h)]
    stats = make_project(OUT / "print" / "plate.stl", spec, f"plate_{tag}", ranges=ranges)
    cfg = slicer.config(spec["print"], spec["filament"], spec["overrides"])
    em = float(str(cfg.get("extrusion_multiplier", "1")).split(",")[0])
    lyr = streamplate.layer(p, c, region, em=em)
    to_bed = streamplate.bed_transform(OUT / "print" / "plate.stl")
    out = OUT / "print" / f"plate_streamlines_{tag}.gcode"
    m = dataclasses.replace(toolpath.Machine.from_config(cfg), max_flow=c.stream_flow)
    info = toolpath.splice(OUT / "gcode" / f"plate_{tag}.gcode", out, lyr, to_bed, m)
    length = sum(float(np.hypot(*np.diff(l, axis=0).T).sum()) for l in lyr.lines)
    cov = streamplate.coverage(lyr, region.buffer(-0.3))
    bands = toolpath.bands(lyr, c.stream_bands)
    minutes = info["minutes"]
    note(f"streamline layer ({tag}): {len(lyr.lines)} lines, {length / 1000:.1f} m, {info['filament_mm']:.0f} mm of filament, "
         f"coverage {cov:.1%}, {info['travel_m']:.1f} m of travel, peak flow {info['peak_mm3_s']:.1f} mm^3/s, "
         f"about {minutes:.0f} min")
    report = [
        "## Streamline layer", "",
        f"Flow snapshot: spectral check passed ({spectra.describe(health)}; `out/renders/flow_spectra.png`).", "",
        f"`out/print/plate_streamlines_{tag}.gcode` is the plate's G-code with the streamline layer spliced in at "
        f"z = {lyr.z:g} mm ({lyr.h:g} mm thick): {len(lyr.lines)} lines, {length / 1000:.1f} m of path, "
        f"{info['filament_mm']:.0f} mm of filament, about {minutes:.0f} min. Coverage {cov:.1%}.", "",
        "Cut list (bands of equal dye-label range, i.e. equal widths of the inlet, in print order). Add about 30 mm to the first piece for the "
        "purge and 80 mm to the last so the extruder can still grip it:", "",
        "| piece | filament (mm) | PETG plate | PLA plate |", "|---|---|---|---|",
        *[f"| {k + 1}{' (outline)' if k == 0 and lyr.n_frame else ''} | {mm:.0f} | "
          f"{toolpath.PALETTES['petg'][2][k % 4][0]} | {toolpath.PALETTES['pla_gold'][2][k % 4][0]} |"
          for k, (_, _, mm) in enumerate(bands)],
    ]
    stats = dict(stats)
    g_layer = info["filament_mm"] * toolpath.A_FIL / 1000 * DENSITY[tag.upper()]
    stats["grams"] = f"{float(stats.get('grams', 0)) + g_layer:.2f}"
    stats["M600"] = str(int(stats.get("M600", "0")) + 2)
    stats["time"] = f"{stats.get('time', '?')} + ~{minutes:.0f} min"
    return stats, report, lyr, bands


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-slice", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--style", choices=("fused", "clamped"), default=CASE.style,
                    help="fused: one-piece case with a camera ring (default); clamped: the v2 bumper and plate")
    args = ap.parse_args(argv)
    p, c = PHONE, dataclasses.replace(CASE, style=args.style)
    for d in ("print", "cad", "profiles", "renders"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = []
    stream_report: list[str] = []
    stream = None  # (layer, bands) for the streamline design

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    if c.style == "fused":
        return build_fused(p, c, args, note, t0)

    # --- geometry -----------------------------------------------------------------
    levels, region = relief(p, c)
    c_rigid = dataclasses.replace(c, fit=c.fit_rigid)  # the PETG bumper: rigid, so a little more clearance
    b, b_rigid = bumper(p, c), bumper(p, c_rigid)
    pl = plate(p, c, relief=levels)
    ph = phone_solid(p)
    for nm, part in (("bumper", b), ("bumper (PETG)", b_rigid), ("plate", pl)):
        assert part.is_valid and len(part.solids()) == 1, f"{nm}: invalid or split into pieces"
    clash = {"bumper/phone": (b & ph).volume, "PETG bumper/phone": (b_rigid & ph).volume,
             "plate/phone": (pl & ph).volume, "bumper/plate": (b & pl).volume}
    note(f"geometry built in {time.time() - t0:.0f} s; overlaps (mm^3): " + ", ".join(f"{k} {v:.3f}" for k, v in clash.items()))
    if levels:
        topo.save_preview([g for g, _ in levels], region, str(OUT / "renders" / "relief_map.png"))

    # Fit tests: the front of the bumper, and the camera end of the plate.
    band = b & box_above(4.0)
    cam_test = pl & box_north_of(p.cam_y - p.cam_h / 2 - 9.0)

    # The bumpers as printed: the CAD plus the grip texture, which only the print mesh carries.
    m_tpu, m_petg = print_mesh(b, p, c), print_mesh(b_rigid, p, c_rigid)
    note(f"textured bumpers at {time.time() - t0:.0f} s ({len(m_tpu.faces)} triangles)")

    # --- exports ------------------------------------------------------------------
    parts = {  # STL name: (part as printed, material, print settings, project name)
        "bumper_tpu": (to_print_bumper(m_tpu, p, c), "TPU", TPU, "bumper_tpu"),
        "bumper_petg": (to_print_bumper(m_petg, p, c_rigid), "PETG", PETG_BUMPER, "bumper_petg"),
        "plate": (to_print_plate(pl), "PETG", PETG, "plate_petg"),
        "test_fit_band": (to_print_bumper(band, p, c), "TPU", TPU, "test_fit_band_tpu"),
        "test_camera": (to_print_plate(cam_test), "PETG", PETG, "test_camera_petg"),
    }
    for nm, (part, *_) in parts.items():
        stl(part, OUT / "print" / f"{nm}.stl")
    b.label, pl.label = "bumper (TPU)", "back plate (PETG)"
    phone_ref = phone_solid(p)
    phone_ref.label = "Pixel 9 Pro XL (reference)"
    bd.export_step(bd.Compound([b, pl, phone_ref]), str(OUT / "cad" / "case_assembly.step"))
    bd.export_step(b, str(OUT / "cad" / "bumper.step"))  # without the grip texture (print mesh only)
    bd.export_step(b_rigid, str(OUT / "cad" / "bumper_petg.step"))
    bd.export_step(pl, str(OUT / "cad" / "plate.step"))
    note(f"exported STL/STEP at {time.time() - t0:.0f} s")

    rows = []
    for nm, (part, mat, spec, project) in parts.items():
        sx, sy, sz = size(part)
        base = dict(part=nm, material=mat, model_g=f"{mass_g(part, mat):.1f}", size=f"{sx:.1f} x {sy:.1f} x {sz:.1f}")
        if args.no_slice:
            rows.append(base)
            continue
        if nm == "plate" and c.design == "streamlines":
            stats, stream_report, lyr, bands = streamline_plate(p, c, region, spec, note)
            stream = (lyr, bands)
            rows.append(base | stats)
            # The bright palette (gold, red, white, clear PLA) needs a PLA plate: PLA does not
            # bond to PETG. PLA softens near 55 C, so PETG stays the default.
            pla_stats, *_ = streamline_plate(p, c, region, PLA, note, tag="pla")
            rows.append(base | dict(part="plate (PLA option)", material="PLA", model_g=f"{mass_g(part, 'PLA'):.1f}") | pla_stats)
            continue
        rows.append(base | make_project(OUT / "print" / f"{nm}.stl", spec, project))
        if nm == "plate" and levels:
            # Two-colour variant: base layers in one filament, terraces + collar in another.
            z_change = round(c.plate_t + c.two_color_level * c.plate_layer, 2)
            rows.append(base | dict(part="plate, two-color") |
                        make_project(OUT / "print" / "plate.stl", spec, "plate_petg_2color",
                                     events=[(z_change, "color", "#1c1d24")]))
    note(f"sliced at {time.time() - t0:.0f} s")

    if not args.no_render:
        from .figures import render_all

        render_all(m_tpu, pl, p, c, OUT / "renders")
        if stream:
            from . import streamplate
            from .figures import flow_spectra, streamline_previews, streamline_renders
            from .streamflow import snapshot

            lyr, bands = stream
            r = snapshot(p, c, c.stream_phase)
            if "dye" in r:  # the smoothed label the toolpaths follow, on ascending grids
                xs, ys, s, (vx, vy) = streamplate.field(r, 0, c.dye_smooth)
                flow = (xs, ys, np.stack([vx, vy]), s)
            else:
                flow = (r["xs"], r["ys"], r["shots"][0], None)
            keep = np.abs(flow[0]) <= p.W / 2 + 0.2  # the figures show the back; the strips past the edges feed the grip
            flow = (flow[0][keep], flow[1], flow[2][:, keep], None if flow[3] is None else flow[3][keep])
            streamline_previews(lyr, region, bands, p, c, OUT / "renders", flow=flow)
            flow_spectra(r, OUT / "renders" / "flow_spectra.png")
            streamline_renders(lyr, bands, m_tpu, pl, p, c, OUT / "renders")
        note(f"rendered at {time.time() - t0:.0f} s")

    # --- report -------------------------------------------------------------------
    lines = ["# Build report", "", f"Built by `python -m case.build` in {time.time() - t0:.0f} s.", "",
             "| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | color changes |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['part']} | {r['material']} | {r['model_g']} | {r['size']} | {r.get('time', '-')} | {r.get('grams', '-')} | {r.get('M600', '-')} |")
    lines += ["", "Overlap check (mm^3, should be 0): " + ", ".join(f"{k} {v:.3f}" for k, v in clash.items()), ""]
    if stream_report:
        lines += stream_report + [""]
    lines += [f"Relief: {c.design}" + (f" ({c.topo_source})" if c.design == "topo" else "")
              + (f", {len(levels)} layers, {sum(h for _, h in levels):.2f} mm tall" if levels else "")]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    note(f"done in {time.time() - t0:.0f} s")


def build_fused(p: Phone, c: Case, args, note, t0: float) -> None:
    """The fused case (case/shell.py): the main part (PETG back and TPU walls, one print) and the
    camera ring (PETG)."""
    from . import fused, shell, toolpath

    body = shell.main_part(p, c)
    back, walls = shell.split(body, p, c)
    ring = shell.camera_ring(p, c)
    for nm, part in (("case", body), ("back (PETG)", back), ("walls (TPU)", walls), ("camera ring", ring)):
        assert part.is_valid and len(part.solids()) == 1, f"{nm}: invalid or split into pieces"
    ph = phone_solid(p)
    clash = {"case/phone": (body & ph).volume, "ring/phone": (ring & ph).volume, "ring/case": (ring & body).volume}
    note(f"geometry built in {time.time() - t0:.0f} s; overlaps (mm^3): " + ", ".join(f"{k} {v:.3f}" for k, v in clash.items()))
    m_petg, m_tpu, m_ring = fused.print_meshes(p, c, (back, walls, ring))
    note(f"print meshes at {time.time() - t0:.0f} s ({len(m_tpu.faces)} triangles in the textured walls)")

    # --- exports ------------------------------------------------------------------
    for nm, m in (("case_back_petg", m_petg), ("case_walls_tpu", m_tpu), ("camera_ring", m_ring)):
        m.export(OUT / "print" / f"{nm}.stl")
    body.label, ring.label = "case (PETG back + TPU walls)", "camera ring (PETG)"
    phone_ref = phone_solid(p)
    phone_ref.label = "Pixel 9 Pro XL (reference)"
    bd.export_step(bd.Compound([back, walls, ring, phone_ref]), str(OUT / "cad" / "fused_assembly.step"))
    bd.export_step(body, str(OUT / "cad" / "case_fused.step"))  # without the grip texture (print mesh only)
    bd.export_step(ring, str(OUT / "cad" / "camera_ring.step"))
    note(f"exported STL/STEP at {time.time() - t0:.0f} s")

    def size_of(*ms):
        lo = np.min([m.bounds[0] for m in ms], axis=0); hi = np.max([m.bounds[1] for m in ms], axis=0)
        return " x ".join(f"{v:.1f}" for v in hi - lo)

    g_petg, g_tpu = m_petg.volume / 1000 * DENSITY["PETG"], m_tpu.volume / 1000 * DENSITY["TPU"]
    rows = [dict(part="case (main part)", material="PETG back + TPU walls", model_g=f"{g_petg:.1f} + {g_tpu:.1f}",
                 size=size_of(m_petg, m_tpu)),
            dict(part="camera ring", material="PETG", model_g=f"{m_ring.volume / 1000 * DENSITY['PETG']:.1f}",
                 size=size_of(m_ring))]
    stream_report, r = [], None
    if not args.no_slice:
        r = fused.build_main(p, c, m_petg, m_tpu, note)
        lyr, bands, info = r["layer"], r["bands"], r["info"]
        grams = [float(g) for g in r["stats"].get("grams", "0, 0").split(",")]
        g_layer = info["filament_mm"] * toolpath.A_FIL / 1000 * DENSITY["PETG"]
        grams[0] += g_layer - info["removed_mm"] * toolpath.A_FIL / 1000 * DENSITY["PETG"]  # the layer replaces the slicer's
        h, mnt = divmod(round(r["minutes"]), 60)
        rows[0] |= dict(time=f"~{h}h {mnt:02d}m", grams=f"{grams[0]:.1f} PETG ({g_layer:.1f} of it the streamline layer) + "
                                                        f"{grams[-1]:.1f} TPU", M600=str(r["M600"]))
        rows[1] |= make_project(OUT / "print" / "camera_ring.stl", RING, "camera_ring_petg")
        stream_report = [
            "## Main part: print sequence", "",
            "`out/print/case_streamlines_petg.gcode` is the print (`out/print/case_fused.3mf` is the project, for "
            "inspection: slicing it gives a plain first layer). One job, three M600 stops:", "",
            "1. Black PETG: purge line and a 5 mm brim.",
            f"2. M600: the streamline layer, {lyr.h:g} mm, the back's visible face: {len(lyr.lines)} lines, "
            f"{r['length'] / 1000:.1f} m of path, {info['filament_mm']:.0f} mm of filament, about {info['minutes']:.0f} min, "
            f"fed piece by piece (cut list below). Coverage {r['coverage']:.1%}.",
            f"3. M600: black PETG for the rest of the back ({c.back_layers} layers of {c.back_layer:g} mm; the top is ironed).",
            f"4. M600: TPU for the walls. The first {fused.HOT_LAYERS} TPU layers print at {fused.HOT} C with the fan off, "
            f"for the bond to the PETG; then the TPU's own temperature and a {fused.BED_TPU} C bed.", "",
            f"Supports: organic, on painted enforcers only; {len(r['enforcers'])} overhangs needed one. The lips' "
            "undersides are 45 degrees, and the openings' tops bridge.", "",
            f"Flow snapshot: spectral check passed ({spectra_describe(r['health'])}; `out/renders/flow_spectra.png`).", "",
            "Cut list for the streamline layer (bands of equal dye-label range, in print order). Add about 30 mm to the "
            "first piece for the purge and 80 mm to the last so the extruder can still grip it:", "",
            "| piece | filament (mm) | color |", "|---|---|---|",
            *[f"| {k + 1}{' (outline)' if k == 0 and lyr.n_frame else ''} | {mm:.0f} | "
              f"{toolpath.PALETTES['petg'][2][k % 4][0]} |" for k, (_, _, mm) in enumerate(bands)],
        ]
    note(f"sliced at {time.time() - t0:.0f} s")

    if not args.no_render:
        from .figures import flow_spectra, fused_renders, fused_sections, print_sequence, streamline_previews

        walls_m = m_tpu.copy()
        walls_m.apply_translation([0, 0, -c.back_t])  # back to the phone frame
        fused_sections(walls_m, back, ring, p, c, OUT / "renders" / "fused_sections.png")
        if r is not None:
            from . import streamplate
            from .geom import rr_shp
            from .streamflow import snapshot

            snap = snapshot(p, c, c.stream_phase)
            xs, ys, s_, (vx, vy) = streamplate.field(snap, 0, c.dye_smooth)
            keep = np.abs(xs) <= c.outer_W(p) / 2 + 0.2
            flow = (xs[keep], ys, np.stack([vx, vy])[:, keep], s_[keep])
            outer = rr_shp(c.outer_W(p), c.outer_L(p), c.outer_corner_r)
            streamline_previews(r["layer"], shell.back_face(p, c), r["bands"], p, c, OUT / "renders", flow=flow, outer=outer,
                                rim="#2a2d3a", palettes=("petg",))  # PETG only: the layer bonds to the PETG back
            flow_spectra(snap, OUT / "renders" / "flow_spectra.png")
            fused_renders(walls_m, back, ring, r["layer"], r["bands"], p, c, OUT / "renders")
            print_sequence(r["gcode"], r["layer"], r["bands"], lambda q: np.asarray(q) + fused.BED_CENTER, c.back_t,
                           OUT / "renders" / "print_sequence.png")
        note(f"rendered at {time.time() - t0:.0f} s")

    # --- report -------------------------------------------------------------------
    lines = ["# Build report (fused case)", "", f"Built by `python -m case.build` in {time.time() - t0:.0f} s.", "",
             "| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | color changes |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['part']} | {row['material']} | {row['model_g']} | {row['size']} | {row.get('time', '-')} | "
                     f"{row.get('grams', '-')} | {row.get('M600', '-')} |")
    lines += ["", "Overlap check (mm^3, should be 0): " + ", ".join(f"{k} {v:.3f}" for k, v in clash.items()), ""]
    lines += stream_report
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    note(f"done in {time.time() - t0:.0f} s")


def spectra_describe(health) -> str:
    from . import spectra

    return spectra.describe(health)


if __name__ == "__main__":
    main()
