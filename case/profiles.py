"""Print settings on top of Prusa's presets, shared by the build and the fused case."""

from __future__ import annotations

import pathlib

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

# ---- fused case (case/shell.py, case/fused.py) ---------------------------------------------
# One print: PETG back, then TPU walls, on Prusa's MK3S+ 0.6 nozzle profile in single-extruder
# multi-material mode with a manual swap. Organic supports refuse per-height layer ranges, so
# one layer height serves both materials above the first layer: the TPU walls' 0.12 mm.
FUSED = dict(
    BUMPER, first_layer_speed=20, elefant_foot_compensation=0,  # the first layer is the hand-fed one, not sliced
    max_layer_height=0.45,  # the 0.45 mm first layer; Prusa's 0.6 nozzle profile stops at 0.40
    skirts=0, brim_type="outer_only", brim_width=5,
    # All top surfaces: mostly the cavity floor. A 0.6 nozzle's flat is over 1 mm wide, so 0.2 mm
    # spacing still overlaps each pass several times over, at half the time of the 0.1 default.
    ironing=1, ironing_type="top", ironing_spacing=0.2, ironing_speed=20,
    # Supports only where support enforcers are painted (case/fused.py paints them on every
    # overhang past the threshold), organic, with the wide gaps Prusa advises for flex, so TPU
    # branches peel off a TPU part.
    support_material=1, support_material_auto=0, support_material_style="organic", support_material_threshold=55,
    support_material_contact_distance=0.3, support_material_bottom_contact_distance=0.3,
    support_material_xy_spacing="100%", support_material_interface_layers=2, dont_support_bridges=1,
    support_material_extruder=0, support_material_interface_extruder=0,
    fill_density="25%", fill_pattern="gyroid",
)
PETG_FUSED = dict(  # extruder 1: the streamline layer and the black back
    filament_settings_id="Prusament PETG (phone-case back)",
    temperature=250, first_layer_temperature=250,
    filament_retract_length=0.8, filament_retract_lift=0.2, filament_wipe=1,
)
TPU_FUSED = dict(  # extruder 2: the walls. Its first layers print hot, for the bond to the PETG (case/fused.py)
    {k: v for k, v in TPU["overrides"].items() if k not in BUMPER and k not in ("fill_density", "fill_pattern")},
    filament_settings_id="TPU 95A (phone-case walls)",
)
RING = dict(  # the camera ring, black PETG, flange down
    print="0.15mm DETAIL @0.6 nozzle MK3", filament="Prusament PETG @0.6 nozzle",
    overrides=dict(
        PETG_BUMPER["overrides"], filament_settings_id="Prusament PETG (phone-case camera ring)",
        first_layer_height=0.24,  # + 2 x 0.12 = the 0.48 mm flange
        skirts=0, brim_type="outer_only", brim_width=5, ironing=1, ironing_type="top",
        support_material=1, support_material_auto=0, support_material_style="organic",
    ),
)
