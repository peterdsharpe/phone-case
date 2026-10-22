# Build report

Built by `python -m case.build` in 42 s.

| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | colour changes |
|---|---|---|---|---|---|---|
| bumper_tpu | TPU | 10.9 | 79.6 x 165.8 x 11.7 | 1h 40m 1s | 10.88 | 0 |
| bumper_petg | PETG | 11.7 | 79.8 x 166.0 x 11.7 | 1h 33m 0s | 11.88 | 0 |
| plate | PETG | 17.8 | 76.1 x 162.3 x 4.6 | 44m 13s + ~27 min | 23.31 | 2 |
| plate (PLA option) | PLA | 17.3 | 76.1 x 162.3 x 4.6 | 42m 39s + ~27 min | 22.75 | 2 |
| test_fit_band | TPU | 5.7 | 79.6 x 165.8 x 5.9 | 51m 41s | 5.74 | 0 |
| test_camera | PETG | 3.8 | 76.1 x 44.5 x 4.6 | 18m 10s | 3.96 | 0 |

Overlap check (mm^3, should be 0): bumper/phone 0.000, PETG bumper/phone 0.000, plate/phone 0.000, bumper/plate 0.000

## Streamline layer

Flow snapshot: spectral check passed (divergence/vorticity variance 2.1e-05 (limit 1e-03), enstrophy high/mid band 1.1e-06 (limit 1e-02), bump near Nyquist: no; `out/renders/flow_spectra.png`).

`out/print/plate_streamlines_petg.gcode` is the plate's G-code with the streamline layer spliced in at z = 1.7 mm (0.45 mm thick): 780 lines, 15.6 m of path, 1714 mm of filament, about 27 min. Coverage 97.5%.

Cut list (bands of equal dye-label range, i.e. equal widths of the inlet, in print order). Add about 30 mm to the first piece for the purge and 80 mm to the last so the extruder can still grip it:

| piece | filament (mm) | PETG plate | PLA plate |
|---|---|---|---|
| 1 (outline) | 73 | white | gold |
| 2 | 17 | Galaxy Black | white |
| 3 | 40 | white | matte red |
| 4 | 40 | translucent | black |
| 5 | 118 | white | gold |
| 6 | 271 | Galaxy Black | white |
| 7 | 249 | white | matte red |
| 8 | 347 | translucent | black |
| 9 | 189 | white | gold |
| 10 | 77 | Galaxy Black | white |
| 11 | 75 | white | matte red |
| 12 | 133 | translucent | black |
| 13 | 84 | white | gold |

Relief: streamlines
