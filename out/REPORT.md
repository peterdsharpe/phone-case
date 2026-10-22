# Build report (fused case)

Built by `python -m case.build` in 21 s.

| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | color changes |
|---|---|---|---|---|---|---|
| case (main part) | PETG back + TPU walls | 16.6 + 7.1 | 79.6 x 165.8 x 11.1 | ~3h 05m | 18.1 PETG (6.1 of it the streamline layer) + 7.0 TPU | 3 |
| camera ring | PETG | 1.6 | 76.2 x 28.2 x 4.6 | 15m 49s | 1.90 | 0 |

Overlap check (mm^3, should be 0): case/phone 0.000, ring/phone 0.000, ring/case 0.000

## Main part: print sequence

`out/print/case_streamlines_petg.gcode` is the print (`out/print/case_fused.3mf` is the project, for inspection: slicing it gives a plain first layer). One job, three M600 stops:

1. Black PETG: purge line and a 5 mm brim.
2. M600: the streamline layer, 0.45 mm, the back's visible face: 903 lines, 18.4 m of path, 2007 mm of filament, about 37 min, fed piece by piece (cut list below). Coverage 97.4%.
3. M600: black PETG for the rest of the back (6 layers of 0.12 mm; the top is ironed).
4. M600: TPU for the walls. The first 3 TPU layers print at 250 C with the fan off, for the bond to the PETG; then the TPU's own temperature and a 60 C bed.

Supports: organic, on painted enforcers only; 0 overhangs needed one. The lips' undersides are 45 degrees, and the openings' tops bridge.

Flow snapshot: spectral check passed (divergence/vorticity variance 2.1e-05 (limit 1e-03), enstrophy high/mid band 1.1e-06 (limit 1e-02), bump near Nyquist: no; `out/renders/flow_spectra.png`).

Cut list for the streamline layer (bands of equal dye-label range, in print order). Add about 30 mm to the first piece for the purge and 80 mm to the last so the extruder can still grip it:

| piece | filament (mm) | color |
|---|---|---|
| 1 (outline) | 87 | white |
| 2 | 19 | Galaxy Black |
| 3 | 50 | white |
| 4 | 57 | translucent |
| 5 | 116 | white |
| 6 | 280 | Galaxy Black |
| 7 | 341 | white |
| 8 | 377 | translucent |
| 9 | 267 | white |
| 10 | 86 | Galaxy Black |
| 11 | 91 | white |
| 12 | 148 | translucent |
| 13 | 88 | white |
