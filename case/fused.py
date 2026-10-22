"""Build the fused case (case/shell.py): print meshes, the two-material PrusaSlicer project,
and the G-code whose first layer is the hand-fed streamline layer.

The main part prints in one job on the MK3S+:
  1. black PETG: the purge line and a 5 mm brim;
  2. colour change: the streamline layer, fed piece by piece (the back's visible face);
  3. colour change: black PETG for the rest of the back;
  4. material change: TPU for the walls. The first TPU layers print hot with the fan off, for
     the bond to the PETG, and then the nozzle and bed drop to TPU settings.
"""

from __future__ import annotations

import dataclasses
import re
import tempfile

import build123d as bd
import numpy as np
import trimesh

from . import shell, slicer, spectra, streamplate, texture, toolpath
from .params import Case, Phone
from .profiles import FUSED, OUT, PETG_FUSED, TPU_FUSED
from .streamflow import snapshot

PRINT = "0.15mm DETAIL @0.6 nozzle MK3"
PETG_FIL, TPU_FIL = "Prusament PETG @0.6 nozzle", "Ultrafuse TPU-95A"
HOT, HOT_LAYERS, BED_TPU = 250, 3, 60  # first TPU layers at 250 C, fan off; then the bed drops to 60 C
BED_CENTER = (125.0, 105.0)


def mesh(part: bd.Part) -> trimesh.Trimesh:
    with tempfile.TemporaryDirectory() as d:
        bd.export_stl(part, f"{d}/m.stl", tolerance=0.01, angular_tolerance=0.1)
        return trimesh.load(f"{d}/m.stl")


def print_meshes(p: Phone, c: Case, parts=None) -> tuple[trimesh.Trimesh, trimesh.Trimesh, trimesh.Trimesh]:
    """(PETG back, TPU walls, camera ring) as print meshes: the main part back-down with its back
    face at z = 0 and centred on the origin, the walls carrying the grip texture; the ring
    flange-down. parts = (back, walls, ring) as built, else they are built here."""
    if parts is None:
        parts = (*shell.split(shell.main_part(p, c), p, c), shell.camera_ring(p, c))
    petg, tpu, ring = parts
    m_petg, m_tpu = mesh(petg), mesh(tpu)
    if c.grip and c.grip_style == "flow":
        m_tpu = texture.apply(m_tpu, p, c)
    for m in (m_petg, m_tpu):
        m.apply_translation([0, 0, c.back_t])
    ring = mesh(ring)
    ring.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))  # flange down
    ring.apply_translation(-np.r_[ring.bounds.mean(axis=0)[:2], ring.bounds[0, 2]])
    return m_petg, m_tpu, ring


def auto_enforcers(meshes, threshold: float = 55.0, min_area: float = 1.0, wall: float = 1.4,
                   max_bridge: float = 20.0) -> list[trimesh.Trimesh]:
    """Support enforcers painted the automatic way: a box under, and reaching into, every patch
    that overhangs more than `threshold` degrees from vertical, off the bed. Short bridges are
    left alone: the ceiling of an opening through a wall (no wider than the wall, at most
    max_bridge long) prints as a bridge, as the bumper's openings did, and supports inside a TPU
    opening would fuse to it."""
    out = []
    for m in meshes:
        sel = (m.face_normals[:, 2] < -np.sin(np.radians(threshold))) & (m.triangles_center[:, 2] > 0.05)
        for o in meshes:  # a face resting on another part (the TPU walls on the PETG back) is no overhang
            if o is not m and sel.any():
                k = np.flatnonzero(sel)
                sel[k[o.contains(m.triangles_center[k] - [0, 0, 0.02])]] = False
        if not sel.any():
            continue
        for patch in m.submesh([np.flatnonzero(sel)], append=True).split(only_watertight=False):
            if patch.area < min_area:
                continue
            (x0, y0, z0), (x1, y1, z1) = patch.bounds
            if min(x1 - x0, y1 - y0) <= wall + 0.6 and max(x1 - x0, y1 - y0) <= max_bridge:
                continue
            box = trimesh.creation.box(extents=[x1 - x0 + 0.6, y1 - y0 + 0.6, z1 - z0 + 1.4])
            box.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2 - 0.3])
            out.append(box)
    return out


def config(c: Case) -> dict[str, str]:
    common = dict(FUSED, first_layer_height=c.stream_h, layer_height=c.back_layer)
    hot = rf'"M900 K0 ; Filament gcode\nM109 S{HOT} ; the first TPU layers print hot: a better bond to the PETG"'
    return slicer.semm_config(PRINT, PETG_FIL, PETG_FUSED, TPU_FIL, dict(TPU_FUSED, start_filament_gcode=hot), common)


def _second(cfg: dict, key: str) -> str:
    return str(cfg[key]).split(",")[-1]


def interface(text: str, c: Case, cfg: dict) -> str:
    """After the swap to TPU: fan off for the first HOT_LAYERS layers (the TPU's start code
    holds the nozzle at HOT), then the TPU's own temperature, a cooler bed, and the fan it
    would have had."""
    lines = text.splitlines()
    i_swap = next(k for k, s in enumerate(lines) if s.startswith("; manual swap: filament 1 -> 2"))
    z_back = c.back_t + HOT_LAYERS * c.back_layer + 1e-6
    i_back = next(k for k in range(i_swap, len(lines))
                  if lines[k].startswith(";Z:") and float(lines[k][3:]) > z_back)
    fan = None
    for k in range(i_swap, i_back):
        if re.match(r"M106\b|M107\b", lines[k]):
            fan, lines[k] = lines[k], "M107 ; fan off while the TPU bonds to the PETG"
    restore = [f"M104 S{_second(cfg, 'temperature')} ; TPU temperature", f"M140 S{BED_TPU} ; bed for TPU"]
    if fan:
        restore.append(fan)
    lines[i_back + 1:i_back + 1] = restore
    return "\n".join(lines) + "\n"


def build_main(p: Phone, c: Case, m_petg, m_tpu, note) -> dict:
    """Project, G-code and stats for the main part."""
    enf = auto_enforcers([m_petg, m_tpu], wall=c.wall)
    proj = OUT / "print" / "case_fused.3mf"
    vols = [("back (PETG)", m_petg, {"extruder": "1"}), ("walls (TPU)", m_tpu, {"extruder": "2"})]
    vols += [(f"support enforcer {k + 1}", e, {"volume_type": "SupportEnforcer"}) for k, e in enumerate(enf)]
    slicer.write_multipart_3mf(proj, "case", vols, at=BED_CENTER)
    cfg = config(c)
    slicer.write_ini(cfg, OUT / "profiles" / "case_fused.ini",
                     header="PrusaSlicer config for the fused case: PETG back (extruder 1) and TPU walls (extruder 2)\n"
                            "on one nozzle, swapped by hand (M600). Import with File > Import > Import Config.")
    slicer.embed_config(proj, cfg)
    (OUT / "gcode").mkdir(exist_ok=True)
    plain = OUT / "gcode" / "case_fused.gcode"
    plain.unlink(missing_ok=True)
    log = slicer.run(["--export-gcode", "-o", str(plain), str(proj)])
    if not plain.exists():  # PrusaSlicer exits 0 even when it refuses to slice
        raise RuntimeError(f"PrusaSlicer wrote no G-code for the fused case:\n{log}")
    stats = slicer.gcode_stats(plain)
    text = slicer.strip_tool_selects(plain.read_text(errors="ignore"))
    first_min = _first_layer_minutes(text)
    supports = [s for s in text.splitlines() if s.startswith(";TYPE:Support")]

    # The streamline layer, as the first layer, from a flow snapshot that passes the spectral check.
    health = spectra.from_snapshot(snapshot(p, c, c.stream_phase))
    note(f"flow snapshot spectral check ({health['source']} resolution): {spectra.describe(health)}")
    if not spectra.healthy(health):
        raise RuntimeError("the flow snapshot fails the spectral check (grid-scale instability): "
                           f"{spectra.describe(health)}. Pick another Case.stream_phase or fix the solver.")
    em = float(str(cfg.get("extrusion_multiplier", "1")).split(",")[0])
    lyr = streamplate.layer(p, c, shell.back_face(p, c), em=em, z=c.stream_h)
    m = dataclasses.replace(toolpath.Machine.from_config(cfg), print_f=60 * c.stream_speed,
                            travel_f=60 * c.stream_travel, max_flow=c.stream_flow)
    text, info = toolpath.splice_first_layer(text, lyr, lambda pts: np.asarray(pts) + BED_CENTER, m)
    text = interface(text, c, cfg)
    out = OUT / "print" / "case_streamlines_petg.gcode"
    out.write_text(text)
    n600 = sum(1 for s in text.splitlines() if s.startswith("M600"))
    length = sum(float(np.hypot(*np.diff(ln, axis=0).T).sum()) for ln in lyr.lines)
    cov = streamplate.coverage(lyr, shell.back_face(p, c).buffer(-0.3))
    note(f"fused case: {len(enf)} support enforcers ({len(supports)} support sections in the G-code); streamline "
         f"first layer {len(lyr.lines)} lines, {length / 1000:.1f} m, {info['filament_mm']:.0f} mm of filament, "
         f"coverage {cov:.1%}, peak flow {info['peak_mm3_s']:.1f} mm^3/s, about {info['minutes']:.0f} min; "
         f"{n600} M600 in all")
    return dict(stats=stats, layer=lyr, bands=toolpath.bands(lyr, c.stream_bands), info=info, enforcers=enf,
                supports=len(supports), M600=n600, coverage=cov, length=length, gcode=out, project=proj,
                minutes=_minutes(stats.get("time", "")) - first_min + info["minutes"], health=health)


def _minutes(t: str) -> float:
    """'2h 48m 58s' -> minutes."""
    return sum(float(v) * {"d": 1440, "h": 60, "m": 1, "s": 1 / 60}[u] for v, u in re.findall(r"([\d.]+)([dhms])", t))


def _first_layer_minutes(text: str) -> float:
    """PrusaSlicer's estimate for its own first layer (which the streamline layer replaces), from
    the remaining-time (M73 R) at the start and at the second layer."""
    rem = [(k, int(m.group(1))) for k, m in ((k, re.match(r"M73 P\d+ R(\d+)", s)) for k, s in enumerate(text.splitlines())) if m]
    i1 = [k for k, s in enumerate(text.splitlines()) if s == ";LAYER_CHANGE"][1]
    r0 = rem[0][1]
    r1 = next(r for k, r in rem if k > i1)
    return float(r0 - r1)
