"""PrusaSlicer configs and project files, built from Prusa's own bundled presets.

PrusaSlicer's vendor bundle (PrusaResearch.ini) defines presets through chains
of `inherits`. `preset()` flattens one chain; `config()` stacks printer + print +
filament presets and our overrides into one plain config that the PrusaSlicer
command line can load with --load.
"""

from __future__ import annotations

import configparser
import functools
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import zipfile

FLATPAK_ID = "com.prusa3d.PrusaSlicer"
PRINTER = "Original Prusa i3 MK3S & MK3S+ 0.6 nozzle"
DROP_KEYS = {"inherits", "compatible_printers", "compatible_printers_condition", "compatible_prints",
             "compatible_prints_condition", "renamed_from", "alias",
             "default_print_profile", "default_filament_profile", "default_sla_print_profile",
             "default_sla_material_profile", "printer_vendor"}


def _exe() -> str | None:
    return next(filter(None, map(shutil.which, ("prusa-slicer", "PrusaSlicer", "prusa-slicer-console"))), None)


def prusaslicer_cmd() -> list[str]:
    """The PrusaSlicer command line: $PRUSASLICER, else PrusaSlicer on the PATH, else the Flatpak."""
    if os.environ.get("PRUSASLICER"):
        return shlex.split(os.environ["PRUSASLICER"])
    exe = _exe()
    return [exe] if exe else ["flatpak", "run", FLATPAK_ID]


@functools.cache
def vendor_ini() -> pathlib.Path:
    """Prusa's vendor bundle, PrusaResearch.ini: $PRUSASLICER_PROFILES, else the usual install places."""
    env = os.environ.get("PRUSASLICER_PROFILES")
    dirs = [pathlib.Path(env)] if env else []
    if shutil.which("flatpak"):
        for scope in ("--user", "--system"):
            out = subprocess.run(["flatpak", "info", scope, "-l", FLATPAK_ID], capture_output=True, text=True)
            if out.returncode == 0:
                dirs.append(pathlib.Path(out.stdout.strip()) / "files/share/PrusaSlicer/profiles")
    if exe := _exe():  # distro packages and unpacked releases keep the profiles next to bin/
        prefix = pathlib.Path(exe).resolve().parents[1]
        dirs += [prefix / "share/PrusaSlicer/profiles", prefix / "resources/profiles", pathlib.Path(exe).resolve().parent / "resources/profiles"]
    dirs += [pathlib.Path("/usr/share/PrusaSlicer/profiles"),
             pathlib.Path("/Applications/PrusaSlicer.app/Contents/Resources/profiles"),
             pathlib.Path("C:/Program Files/Prusa3D/PrusaSlicer/resources/profiles")]
    for d in dirs:
        f = d if d.suffix == ".ini" else d / "PrusaResearch.ini"
        if f.exists():
            return f
    raise FileNotFoundError("PrusaSlicer's vendor profiles (PrusaResearch.ini) were not found. Set PRUSASLICER_PROFILES "
                            "to that file (it ships in PrusaSlicer's resources/profiles folder), or build with --no-slice.")


@functools.cache
def _sections() -> dict[str, dict[str, str]]:
    cp = configparser.RawConfigParser(strict=False, interpolation=None, comment_prefixes=("#",), inline_comment_prefixes=None)
    cp.optionxform = str
    cp.read(vendor_ini(), encoding="utf-8")
    return {s: dict(cp.items(s)) for s in cp.sections()}


def preset(kind: str, name: str) -> dict[str, str]:
    """Fully resolved preset `kind:name` (kind = print | filament | printer)."""
    secs = _sections()
    key = f"{kind}:{name}"
    if key not in secs:
        raise KeyError(key)
    own = secs[key]
    out: dict[str, str] = {}
    # Parents apply left to right, then the section's own keys (PrusaSlicer's rule).
    for parent in [s.strip().strip('"') for s in own.get("inherits", "").split(";") if s.strip()]:
        out.update(preset(kind, parent))
    out.update(own)
    return out


def config(print_name: str, filament_name: str, overrides: dict[str, object]) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for kind, name in (("printer", PRINTER), ("print", print_name), ("filament", filament_name)):
        cfg.update({k: v for k, v in preset(kind, name).items() if k not in DROP_KEYS})
    cfg["print_settings_id"] = print_name
    cfg["filament_settings_id"] = filament_name
    cfg["printer_settings_id"] = PRINTER
    for k, v in overrides.items():
        cfg[k] = str(int(v) if isinstance(v, bool) else v)
    return cfg


def write_ini(cfg: dict[str, str], path: pathlib.Path, header: str = "") -> None:
    lines = [f"# {line}" for line in header.splitlines()] if header else []
    lines += [f"{k} = {v}" for k, v in sorted(cfg.items())]
    path.write_text("\n".join(lines) + "\n")


def run(args: list[str], cwd: pathlib.Path | None = None) -> str:
    r = subprocess.run(prusaslicer_cmd() + args, capture_output=True, text=True, cwd=cwd)
    log = "\n".join(l for l in (r.stdout + r.stderr).splitlines()
                    if l.strip() and not set(l.strip()) <= {"-"} and "flatpak with entrypoint" not in l and "canberra" not in l)
    if r.returncode != 0:
        raise RuntimeError(f"PrusaSlicer failed ({r.returncode}):\n{log}")
    return log


def gcode_stats(gcode: pathlib.Path) -> dict[str, str]:
    """Print time and filament use from the comment block PrusaSlicer writes at the end."""
    text = gcode.read_text(errors="ignore")[-60000:]
    want = {"estimated printing time (normal mode)": "time", "filament used [g]": "grams",
            "filament used [mm]": "mm", "total layers count": "layers"}
    out = {}
    for line in text.splitlines():
        m = re.match(r";\s*(.+?)\s*=\s*(.+)", line)
        if m and m.group(1) in want:
            out[want[m.group(1)]] = m.group(2)
    return out


def embed_config(project: pathlib.Path, cfg: dict[str, str], version: str = "2.9.6") -> None:
    """Write the print/filament/printer settings into a .3mf, the way PrusaSlicer saves projects."""
    import datetime

    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d at %H:%M:%S UTC")
    text = f"; generated by PrusaSlicer {version}+flathub.org on {now}\n\n" + "".join(f"; {k} = {v}\n" for k, v in sorted(cfg.items()))
    _replace_in_zip(project, {"Metadata/Slic3r_PE.config": text})


def _replace_in_zip(path: pathlib.Path, files: dict[str, str]) -> None:
    tmp = pathlib.Path(tempfile.mkstemp(suffix=".3mf", dir=path.parent)[1])
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.filename not in files:
                zout.writestr(item, zin.read(item.filename))
        for name, text in files.items():
            zout.writestr(name, text)
    shutil.move(tmp, path)
    path.chmod(0o644)


def add_layer_ranges(project: pathlib.Path, ranges: list[tuple[float, float, float]]) -> None:
    """Per-height layer thickness (PrusaSlicer "height range modifiers"), editable in the GUI.

    ranges: (z_min, z_max, layer_height) for object 1."""
    rows = "".join(f'  <range min_z="{a:g}" max_z="{b:g}">\n   <option opt_key="extruder">0</option>\n'
                   f'   <option opt_key="layer_height">{h:g}</option>\n  </range>\n' for a, b, h in ranges)
    xml = f'<?xml version="1.0" encoding="utf-8"?>\n<objects>\n <object id="1">\n{rows} </object>\n</objects>\n'
    _replace_in_zip(project, {"Metadata/Prusa_Slicer_layer_config_ranges.xml": xml})


def add_custom_gcode(project: pathlib.Path, events: list[tuple[float, str, str]]) -> None:
    """Insert colour changes / pauses into a .3mf project (shown in PrusaSlicer's layer slider).

    events: (print_z, type, extra) with type 'color' (M600) or 'pause' (M601)."""
    items = []
    for z, kind, extra in events:
        t = {"color": 0, "pause": 1}[kind]  # CustomGCode::Type: ColorChange=0, PausePrint=1
        items.append(f'<code print_z="{z:.4f}" type="{t}" extruder="1" color="{extra if kind == "color" else ""}" '
                     f'extra="{extra if kind == "pause" else ""}" gcode="{"M600" if kind == "color" else "M601"}"/>')
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_print_z>\n' + "\n".join(items) +
           '\n<mode value="SingleExtruder"/>\n</custom_gcodes_per_print_z>\n')
    _replace_in_zip(project, {"Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml": xml})


# ---- two materials on one nozzle, swapped by hand ------------------------------------------

# Options with one value per extruder in a printer config.
EXTRUDER_KEYS = {"nozzle_diameter", "extruder_colour", "extruder_offset", "max_layer_height", "min_layer_height",
                 "retract_length", "retract_lift", "retract_lift_above", "retract_lift_below", "retract_speed",
                 "deretract_speed", "retract_restart_extra", "retract_before_travel", "retract_layer_change", "wipe",
                 "retract_before_wipe", "retract_length_toolchange", "retract_restart_extra_toolchange"}
_QUOTED = {"start_filament_gcode", "end_filament_gcode", "filament_notes", "filament_ramming_parameters"}
_STRING_VEC = {"filament_type", "filament_colour", "filament_settings_id", "extruder_colour"}


def semm_config(print_name: str, fil1: str, over1: dict, fil2: str, over2: dict, common: dict) -> dict[str, str]:
    """Config for two materials on the MK3S's single nozzle without an MMU: PrusaSlicer's
    single-extruder multi-material mode, no wipe tower, and M600 (unload, wait for the user,
    load, purge) as the tool change. Per-filament and per-extruder options get one value per
    material. PrusaSlicer still writes T0/T1 lines, which the build strips (strip_tool_selects)."""
    c1 = config(print_name, fil1, {**common, **over1})
    c2 = config(print_name, fil2, {**common, **over2})
    fil_keys = (set(preset("filament", fil1)) | set(preset("filament", fil2)) | {
        k for k in {**over1, **over2} if k.startswith(("filament_", "temperature", "first_layer_temperature",
                                                       "bed_temperature", "first_layer_bed_temperature"))
        or k in {"extrusion_multiplier", "min_fan_speed", "max_fan_speed", "bridge_fan_speed", "fan_always_on",
                 "cooling", "disable_fan_first_layers", "start_filament_gcode"}}) - DROP_KEYS
    cfg = dict(c1)
    for k in sorted(fil_keys | EXTRUDER_KEYS):
        if k == "filament_vendor":
            continue
        a, b = c1.get(k, c2.get(k, "")), c2.get(k, c1.get(k, ""))
        if a.startswith('"') or b.startswith('"') or k in _QUOTED:
            q = lambda v: v if v.startswith('"') else f'"{v}"'  # noqa: E731
            cfg[k] = f"{q(a)};{q(b)}"
        elif k in _STRING_VEC:
            cfg[k] = f"{a};{b}"
        else:
            cfg[k] = f"{a},{b}"
    cfg.update({k: str(v) for k, v in dict(
        single_extruder_multi_material=1, wipe_tower=0,
        # Not at the initial tool selection (previous_extruder = -1): only a real swap.
        toolchange_gcode="{if previous_extruder >= 0}; manual swap: filament {previous_extruder+1} -> "
                         "{next_extruder+1} ({filament_type[next_extruder]})\\nM600\\n{endif}",
    ).items()})
    return cfg


def strip_tool_selects(text: str) -> str:
    """Drop PrusaSlicer's T<n> lines: without an MMU the firmware only answers "Invalid extruder"."""
    return "\n".join(s for s in text.splitlines() if not re.fullmatch(r"T\d+\s*", s)) + "\n"


def write_multipart_3mf(path: pathlib.Path, name: str, volumes: list, at=(125.0, 105.0)) -> None:
    """A .3mf with one object made of several volumes: volumes = [(name, trimesh, metadata)],
    metadata like {"extruder": "2"} or {"volume_type": "SupportEnforcer"}. Mesh coordinates are
    the object's (z = 0 on the bed); `at` places the object on the bed."""
    verts, tris, vols, off = [], [], [], 0
    for vname, m, meta in volumes:
        t0 = len(tris)
        verts += [f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in m.vertices]
        tris += [f'     <triangle v1="{a + off}" v2="{b + off}" v3="{c + off}"/>' for a, b, c in m.faces]
        off += len(m.vertices)
        md = "".join(f'\n   <metadata type="volume" key="{k}" value="{v}"/>'
                     for k, v in {"name": vname, "volume_type": "ModelPart", **meta}.items())
        vols.append(f'  <volume firstid="{t0}" lastid="{len(tris) - 1}">{md}\n  </volume>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">\n'
             ' <metadata name="slic3rpe:Version3mf">1</metadata>\n <resources>\n  <object id="1" type="model">\n'
             '   <mesh>\n    <vertices>\n' + "\n".join(verts) + '\n    </vertices>\n    <triangles>\n' + "\n".join(tris) +
             '\n    </triangles>\n   </mesh>\n  </object>\n </resources>\n <build>\n'
             f'  <item objectid="1" transform="1 0 0 0 1 0 0 0 1 {at[0]} {at[1]} 0" printable="1"/>\n </build>\n</model>\n')
    mc = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n <object id="1" instances_count="1">\n'
          f'  <metadata type="object" key="name" value="{name}"/>\n' + "\n".join(vols) + '\n </object>\n</config>\n')
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>\n')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>\n')
    path.unlink(missing_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/Slic3r_PE_model.config", mc)
