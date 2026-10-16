"""Build every output.  Usage:  uv run python -m case.build [--no-slice] [--no-render]

Writes out/print (STL + PrusaSlicer projects), out/cad (STEP), out/profiles (.ini),
out/renders (PNG), and out/REPORT.md (sizes, masses, print times).
"""

from __future__ import annotations

import argparse
import pathlib
import time

import build123d as bd
import numpy as np
import shapely

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
TPU = dict(
    print="0.20mm DETAIL @0.6 nozzle MK3", filament="Generic FLEX",
    overrides=dict(
        perimeters=2, perimeter_generator="arachne",
        perimeter_extrusion_width=0.7, external_perimeter_extrusion_width=0.7,
        fill_density="25%", fill_pattern="gyroid", top_solid_layers=4, bottom_solid_layers=4,
        temperature=245, first_layer_temperature=245,  # +5 C for hardened steel
        filament_max_volumetric_speed=2.0, avoid_crossing_perimeters=1, thick_bridges=1,
        skirts=1, skirt_distance=3, brim_width=0, support_material=0,
        # Looks: 0.15 mm layers smooth the 45-degree lip and the rim fillet for ~2 min more (TPU
        # prints at its flow limit, so thinner layers barely slow it); concentric lines follow the
        # outline on the lip and rim faces instead of crossing the corners diagonally; scarf seams
        # ramp the outer wall's seam in where the contour is smooth.
        layer_height=0.15, first_layer_height=0.2, top_fill_pattern="concentric", bottom_fill_pattern="concentric",
        seam_position="aligned", scarf_seam_placement="contours", scarf_seam_only_on_smooth=1,
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


def to_print_bumper(part: bd.Part, p: Phone, c: Case) -> bd.Part:
    """Lip on the bed: rotate 180 deg about y, front face to z = 0."""
    return bd.Pos(0, 0, c.z_front(p)) * (bd.Rot(0, 180, 0) * part)


def to_print_plate(part: bd.Part) -> bd.Part:
    """Inner face on the bed."""
    return bd.Rot(0, 180, 0) * part


def box_above(z: float, big: float = 400) -> bd.Part:
    return bd.Pos(0, 0, z + big / 2) * bd.Box(big, big, big)


def box_north_of(y: float, big: float = 400) -> bd.Part:
    return bd.Pos(0, y + big / 2, 0) * bd.Box(big, big, big)


def stl(part, path: pathlib.Path):
    bd.export_stl(part, str(path), tolerance=0.01, angular_tolerance=0.1)


def mass_g(part, material: str) -> float:
    return part.volume / 1000 * DENSITY[material]


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
    from . import streamplate, toolpath

    spec = dict(spec, overrides=dict(spec["overrides"], first_layer_height=c.base_layer))
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
    info = toolpath.splice(OUT / "gcode" / f"plate_{tag}.gcode", out, lyr, to_bed, toolpath.Machine.from_config(cfg))
    length = sum(float(np.hypot(*np.diff(l, axis=0).T).sum()) for l in lyr.lines)
    cov = streamplate.coverage(lyr, region.buffer(-0.3))
    bands = toolpath.bands(lyr, c.stream_bands)
    minutes = info["minutes"]
    note(f"streamline layer ({tag}): {len(lyr.lines)} lines, {length / 1000:.1f} m, {info['filament_mm']:.0f} mm of filament, "
         f"coverage {cov:.1%}, {info['travel_m']:.1f} m of travel, peak flow {info['peak_mm3_s']:.1f} mm^3/s, "
         f"about {minutes:.0f} min")
    report = [
        "## Streamline layer", "",
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
    b = bumper(p, c)
    pl = plate(p, c, relief=levels)
    ph = phone_solid(p)
    for nm, part in (("bumper", b), ("plate", pl)):
        assert part.is_valid and len(part.solids()) == 1, f"{nm}: invalid or split into pieces"
    clash = {"bumper/phone": (b & ph).volume, "plate/phone": (pl & ph).volume, "bumper/plate": (b & pl).volume}
    note(f"geometry built in {time.time() - t0:.0f} s; overlaps (mm^3): " + ", ".join(f"{k} {v:.3f}" for k, v in clash.items()))
    if levels:
        topo.save_preview([g for g, _ in levels], region, str(OUT / "renders" / "relief_map.png"))

    # Fit tests: the front of the bumper, and the camera end of the plate.
    band = b & box_above(4.0)
    cam_test = pl & box_north_of(p.cam_y - p.cam_h / 2 - 9.0)

    # --- exports ------------------------------------------------------------------
    parts = {
        "bumper": (to_print_bumper(b, p, c), "TPU", TPU),
        "plate": (to_print_plate(pl), "PETG", PETG),
        "test_fit_band": (to_print_bumper(band, p, c), "TPU", TPU),
        "test_camera": (to_print_plate(cam_test), "PETG", PETG),
    }
    for nm, (part, mat, _) in parts.items():
        stl(part, OUT / "print" / f"{nm}.stl")
    b.label, pl.label = "bumper (TPU)", "back plate (PETG)"
    phone_ref = phone_solid(p)
    phone_ref.label = "Pixel 9 Pro XL (reference)"
    bd.export_step(bd.Compound([b, pl, phone_ref]), str(OUT / "cad" / "case_assembly.step"))
    bd.export_step(b, str(OUT / "cad" / "bumper.step"))
    bd.export_step(pl, str(OUT / "cad" / "plate.step"))
    note(f"exported STL/STEP at {time.time() - t0:.0f} s")

    rows = []
    for nm, (part, mat, spec) in parts.items():
        bb = part.bounding_box()
        base = dict(part=nm, material=mat, model_g=f"{mass_g(part, mat):.1f}",
                    size=f"{bb.size.X:.1f} x {bb.size.Y:.1f} x {bb.size.Z:.1f}")
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
        rows.append(base | make_project(OUT / "print" / f"{nm}.stl", spec, f"{nm}_{mat.lower()}"))
        if nm == "plate" and levels:
            # Two-colour variant: base layers in one filament, terraces + collar in another.
            z_change = round(c.plate_t + c.two_color_level * c.plate_layer, 2)
            rows.append(base | dict(part="plate, two-colour") |
                        make_project(OUT / "print" / "plate.stl", spec, "plate_petg_2color",
                                     events=[(z_change, "color", "#1c1d24")]))
    note(f"sliced at {time.time() - t0:.0f} s")

    if not args.no_render:
        from .figures import render_all

        render_all(b, pl, p, c, OUT / "renders")
        if stream:
            from .figures import streamline_previews, streamline_renders
            from .streamflow import snapshot

            lyr, bands = stream
            r = snapshot(p, c, c.stream_phase)
            flow = (r["xs"], r["ys"], r["shots"][0], r["dye"][0] if "dye" in r else None)
            streamline_previews(lyr, region, bands, p, c, OUT / "renders", flow=flow)
            streamline_renders(lyr, bands, b, pl, p, c, OUT / "renders")
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
