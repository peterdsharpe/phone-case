# Build report

Built by `python -m case.build` in 52 s.

| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | colour changes |
|---|---|---|---|---|---|---|
| bumper_tpu | TPU | 10.9 | 79.6 x 165.8 x 11.7 | 1h 40m 1s | 10.88 | 0 |
| bumper_petg | PETG | 11.7 | 79.8 x 166.0 x 11.7 | 1h 33m 0s | 11.88 | 0 |
| plate | PETG | 17.8 | 76.1 x 162.3 x 4.6 | 44m 47s + ~16 min | 21.01 | 2 |
| plate (PLA option) | PLA | 17.3 | 76.1 x 162.3 x 4.6 | 43m 4s + ~16 min | 20.51 | 2 |
| test_fit_band | TPU | 5.7 | 79.6 x 165.8 x 5.9 | 51m 41s | 5.74 | 0 |
| test_camera | PETG | 3.8 | 76.1 x 44.5 x 4.6 | 18m 10s | 3.96 | 0 |

Overlap check (mm^3, should be 0): bumper/phone 0.000, PETG bumper/phone 0.000, plate/phone 0.000, bumper/plate 0.000

## Streamline layer

Flow snapshot: spectral check passed (divergence/vorticity variance 2.1e-05 (limit 1e-03), enstrophy high/mid band 1.1e-06 (limit 1e-02), bump near Nyquist: no; `out/renders/flow_spectra.png`).

`out/print/plate_streamlines_petg.gcode` is the plate's G-code with the streamline layer spliced in at z = 1.5 mm (0.25 mm thick): 794 lines, 15.7 m of path, 957 mm of filament, about 16 min. Coverage 96.6%.

Cut list (bands of equal dye-label range, i.e. equal widths of the inlet, in print order). Add about 30 mm to the first piece for the purge and 80 mm to the last so the extruder can still grip it:

| piece | filament (mm) | PETG plate | PLA plate |
|---|---|---|---|
| 1 (outline) | 41 | white | gold |
| 2 | 10 | Galaxy Black | white |
| 3 | 22 | white | matte red |
| 4 | 22 | translucent | black |
| 5 | 65 | white | gold |
| 6 | 151 | Galaxy Black | white |
| 7 | 140 | white | matte red |
| 8 | 195 | translucent | black |
| 9 | 105 | white | gold |
| 10 | 43 | Galaxy Black | white |
| 11 | 42 | white | matte red |
| 12 | 74 | translucent | black |
| 13 | 47 | white | gold |

Relief: streamlines
