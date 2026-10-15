"""Build every output.  Usage:  uv run python -m case.build [--no-slice] [--no-render]

Writes out/print (STL + PrusaSlicer projects), out/cad (STEP), out/profiles (.ini),
out/renders (PNG), and out/REPORT.md (sizes, masses, print times).
"""

from __future__ import annotations

import argparse
import math
import pathlib
import time

import build123d as bd

from . import slicer, topo
from .bumper import bumper
from .geom import outline_shp, stadium_shp
from .params import CASE, PHONE, Case, Phone
from .phone import phone_parts, phone_solid
from .plate import collar_size, plate

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "out"
DENSITY = {"TPU": 1.21, "PETG": 1.27}  # g/cm^3

# Print settings on top of Prusa's presets (MK3S+, 0.6 mm hardened-steel nozzle).
TPU = dict(
    print="0.20mm DETAIL @0.6 nozzle MK3", filament="Generic FLEX",
    overrides=dict(
        perimeters=2, perimeter_generator="arachne",
        perimeter_extrusion_width=0.7, external_perimeter_extrusion_width=0.7,
        fill_density="25%", fill_pattern="gyroid", top_solid_layers=4, bottom_solid_layers=4,
        temperature=245, first_layer_temperature=245,  # +5 C for hardened steel
        filament_max_volumetric_speed=2.0, avoid_crossing_perimeters=1, thick_bridges=1,
        seam_position="rear", skirts=1, skirt_distance=3, brim_width=0, support_material=0,
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


def relief(p: Phone, c: Case):
    if not c.topo_source:
        return None, None
    cl, ch = collar_size(p, c)
    region = outline_shp(p, c.flange_reach + c.topo_margin).difference(
        stadium_shp(cl + 2 * c.topo_collar_margin, ch + 2 * c.topo_collar_margin, 0, p.cam_y))
    return topo.terraces(c.topo_source, region, c.topo_levels, c.topo_min_feature), region


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


def make_project(stl_path: pathlib.Path, spec: dict, name: str, events=None) -> dict[str, str]:
    """PrusaSlicer project (.3mf with settings) next to the STL; slice it to verify; return stats."""
    cfg = slicer.config(spec["print"], spec["filament"], spec["overrides"])
    ini = OUT / "profiles" / f"{name}.ini"
    slicer.write_ini(cfg, ini, header=f"PrusaSlicer config for {name}: {slicer.PRINTER} + {spec['print']} + {spec['filament']} + overrides.\nImport with File > Import > Import Config.")
    proj = stl_path.with_suffix(".3mf").with_name(f"{name}.3mf")
    slicer.run(["--load", str(ini), "--center", "125,105", "--export-3mf", "-o", str(proj), str(stl_path)])
    slicer.embed_config(proj, cfg)
    if events:
        slicer.add_custom_gcode(proj, events)
    gdir = OUT / "gcode"
    gdir.mkdir(exist_ok=True)
    gcode = gdir / f"{name}.gcode"
    slicer.run(["--export-gcode", "-o", str(gcode), str(proj)])  # slice the project itself
    stats = slicer.gcode_stats(gcode)
    text = gcode.read_text(errors="ignore")
    stats["M600"] = str(sum(1 for line in text.splitlines() if line.startswith("M600")))
    stats["M601"] = str(sum(1 for line in text.splitlines() if line.startswith("M601")))
    return stats


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
        topo.save_preview(levels, region, str(OUT / "renders" / "topo_map.png"))

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
        rows.append(base | make_project(OUT / "print" / f"{nm}.stl", spec, f"{nm}_{mat.lower()}"))
        if nm == "plate" and levels:
            # Two-colour variant: base layers in one filament, terraces + collar in another.
            z_change = round(c.plate_t + c.two_color_level * c.topo_step, 2)
            rows.append(base | dict(part="plate, two-colour") |
                        make_project(OUT / "print" / "plate.stl", spec, "plate_petg_2color",
                                     events=[(z_change, "color", "#1c1d24")]))
    note(f"sliced at {time.time() - t0:.0f} s")

    if not args.no_render:
        from .figures import render_all

        render_all(b, pl, p, c, OUT / "renders")
        note(f"rendered at {time.time() - t0:.0f} s")

    # --- report -------------------------------------------------------------------
    lines = ["# Build report", "", f"Built by `python -m case.build` in {time.time() - t0:.0f} s.", "",
             "| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | colour changes |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['part']} | {r['material']} | {r['model_g']} | {r['size']} | {r.get('time', '-')} | {r.get('grams', '-')} | {r.get('M600', '-')} |")
    lines += ["", "Overlap check (mm^3, should be 0): " + ", ".join(f"{k} {v:.3f}" for k, v in clash.items()), ""]
    lines += ["Topography: " + (c.topo_source or "none") + (f", {len(levels)} terraces of {c.topo_step} mm" if levels else "")]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")
    note(f"done in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
