# Build report

Built by `python -m case.build` in 19 s.

| part | material | model mass (g) | size as printed (mm) | print time | filament (g, slicer) | colour changes |
|---|---|---|---|---|---|---|
| bumper | TPU | 11.3 | 79.6 x 165.8 x 11.8 | 1h 29m 32s | 13.16 | 0 |
| plate | PETG | 17.8 | 76.1 x 162.3 x 4.6 | 44m 47s + ~14 min | 21.05 | 2 |
| plate (PLA option) | PLA | 17.3 | 76.1 x 162.3 x 4.6 | 43m 4s + ~14 min | 20.55 | 2 |
| test_fit_band | TPU | 5.6 | 79.6 x 165.8 x 5.9 | 45m 0s | 6.70 | 0 |
| test_camera | PETG | 3.8 | 76.1 x 44.5 x 4.6 | 18m 10s | 3.96 | 0 |

Overlap check (mm^3, should be 0): bumper/phone 0.000, plate/phone 0.000, bumper/plate 0.000

## Streamline layer

`out/print/plate_streamlines_petg.gcode` is the plate's G-code with the streamline layer spliced in at z = 1.5 mm (0.25 mm thick): 478 lines, 16.2 m of path, 967 mm of filament, about 14 min. Coverage 99.3%.

Cut list (equal stream-function bands, in print order). Add about 30 mm to the first piece for the purge and 80 mm to the last so the extruder can still grip it:

| piece | filament (mm) | PETG plate | PLA plate |
|---|---|---|---|
| 1 | 83 | white | gold |
| 2 | 103 | Galaxy Black | white |
| 3 | 84 | white | matte red |
| 4 | 81 | translucent | black |
| 5 | 81 | white | gold |
| 6 | 73 | Galaxy Black | white |
| 7 | 59 | white | matte red |
| 8 | 53 | translucent | black |
| 9 | 71 | white | gold |
| 10 | 177 | Galaxy Black | white |
| 11 | 56 | white | matte red |
| 12 | 47 | translucent | black |

Relief: streamlines
