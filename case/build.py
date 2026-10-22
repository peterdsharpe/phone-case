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

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
DENSITY = {"TPU": 1.21, "PETG": 1.27, "PLA": 1.24}  # g/cm^3

# Print settings on top of Prusa's presets (MK3S+, 0.6 mm hardened-steel nozzle).
# The bumpers are tuned for finish. 0.12 mm layers smooth the walls and 45-degree faces; Prusa's
# profile stops at 0.15 for this nozzle (lifted below), and much thinner than 0.1 the wide nozzle
# face drags on the layer below and the flow gets erratic.
BUMPER = dict(
    min_layer_height=0.07, layer_height=0.12, first_layer_height=0.15,
    perimeters=2, perimeter_generator="arachne",
    perimeter_extrusion_width=0.7, external_perimeter_extrusion_width=0.7,
    top_solid_layers=6, bottom_solid_layers=6, top_fill_pattern="concentric", bottom_fill_pattern="concentric",
    external_perimeter_speed=25, perimeter_speed=35, small_perimeter_speed=20, first_layer_speed=15,
    # Overhangs (the bottom openings, the rim's bevel): slower and cooler the more a line overhangs.
    enable_dynamic_overhang_speeds=1, overhang_speed_0=12, overhang_speed_1=15, overhang_speed_2=20, overhang_speed_3=25,
    bridge_speed=20, thick_bridges=0,
    # Seams at the top end, away from the inside corners; scarf joints ramp them in where the contour is smooth.
    seam_position="rear", seam_gap="10%", staggered_inner_seams=1,
    scarf_seam_placement="everywhere", scarf_seam_only_on_smooth=1, scarf_seam_length=15,
    # Travel stays inside the ring, so no strings cross the cavity or the openings.
    avoid_crossing_perimeters=1, travel_speed=180,
    elefant_foot_compensation=0.15, skirts=1, skirt_distance=3, brim_width=0, support_material=0,
)
TPU = dict(  # a 95A TPU; Prusa's MK3-compatible Ultrafuse TPU-95A preset is the closest match
    print="0.15mm DETAIL @0.6 nozzle MK3", filament="Ultrafuse TPU-95A",
    overrides=dict(
        BUMPER, filament_settings_id="TPU 95A (phone-case bumper)",
        fill_density="25%", fill_pattern="gyroid",
        temperature=235, first_layer_temperature=235,  # 10 C below the first print: less stringing at this low flow
        bed_temperature=50, first_layer_bed_temperature=50,
        filament_max_volumetric_speed=1.8, extrusion_multiplier=1.05,  # Generic FLEX's 1.15 over-extrudes a 95A
        filament_retract_length=0.8, filament_retract_speed=25, filament_deretract_speed=20,
        filament_retract_lift=0, filament_retract_before_travel=2, filament_wipe=0,  # no z-hop: it strings
        min_fan_speed=40, max_fan_speed=70, bridge_fan_speed=80, fan_always_on=1,
    ),
)
PETG_BUMPER = dict(
    print="0.15mm DETAIL @0.6 nozzle MK3", filament="Prusament PETG @0.6 nozzle",
    overrides=dict(
        BUMPER, filament_settings_id="Prusament PETG (phone-case bumper)",
        fill_density="100%", fill_pattern="rectilinear",
        temperature=240, first_layer_temperature=240,  # 10 C below the first print; inside Prusament's 250 +- 10
        filament_max_volumetric_speed=10,
        filament_retract_length=0.8, filament_retract_lift=0.2, filament_wipe=1,
        bridge_fan_speed=80, enable_dynamic_fan_speeds=1,
        overhang_fan_speed_0=90, overhang_fan_speed_1=70, overhang_fan_speed_2=50, overhang_fan_speed_3=35,
    ),
)
PETG = dict(
    print="0.15mm DETAIL @0.6 nozzle MK3", filament="Prusament PETG @0.6 nozzle",
    overrides=dict(
        perimeters=2, perimeter_generator="arachne", top_solid_layers=5, bottom_solid_layers=4,
        fill_density="100%", fill_pattern="rectilinear",  # solid: stiff, and no infill pattern behind clear PETG
        temperature=250, first_layer_temperature=250,  # +10 C for hardened steel at 0.6 flow
        top_fill_pattern="monotonic", seam_position="rear", skirts=1, skirt_distance=3,
        brim_width=0, support_material=0,
    ),
)
# PLA plate, for the streamline layer's bright palette. +10 C for hardened steel, as for PETG.
PLA = dict(PETG, filament="Prusament PLA", overrides=dict(PETG["overrides"], temperature=225, first_layer_temperature=225))


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
    args = ap.parse_args(argv)
    p, c = PHONE, CASE
    for d in ("print", "cad", "profiles", "renders"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = []
    stream_report: list[str] = []
    stream = None  # (layer, bands) for the streamline design

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

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
            rows.append(base | dict(part="plate, two-colour") |
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
             "| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | colour changes |",
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


if __name__ == "__main__":
    main()
