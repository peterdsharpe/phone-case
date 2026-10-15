# Measuring the phone

The model starts from Google's published size (162.8 × 76.6 × 8.5 mm) plus
positions measured from ten community Pixel 9 Pro XL cases, one of which came
with its author's caliper measurements. Before the full print, measure the
items below. Then edit `case/params.py` (class `Phone`) and rebuild with
`uv run python -m case.build`.

Do this with the phone bare (no screen protector or skin). Each distance runs
from the stated edge to the stated feature, along the phone's long or short
axis. "Top" is the camera end. "Right" is the power-button side, seen from the
screen.

| # | What | How | Parameter | Model value | Range in references |
|---|---|---|---|---|---|
| 1 | Width | calipers across the flat sides, at mid-height | `W` | 76.6 | spec |
| 2 | Height | calipers end to end | `L` | 162.8 | spec |
| 3 | Thickness | calipers on the glass, away from the camera bar | `T` | 8.5 | spec |
| 4 | Camera bar length | outside of the pill where it meets the glass | `cam_len` | 70.6 | 69.2–70.6 |
| 5 | Camera bar height | short direction of the pill, at the glass | `cam_h` | 22.6 | 21.75–22.6 |
| 6 | Top edge to camera bar | top edge of the phone to the top of the pill | `cam_top` | 13.15 | 13.0–13.6 |
| 7 | Camera bar height above the glass | calipers' depth rod, or total thickness at the bar minus #3 | `cam_proud` | 3.6 | 3.5–3.6 |
| 8 | Top edge to power button (top end) | along the right side | `power_top` | 43.4 | 43.3–43.4 |
| 9 | Power button length | | `power_len` | 12.0 | 12 |
| 10 | Top edge to volume rocker (top end) | | `vol_top` | 62.2 | 62.0–62.2 |
| 11 | Volume rocker length | | `vol_len` | 22.0 | 22 |
| 12 | Speaker grille, left and right ends | x from the centre line, seen from the screen; left is negative | `spk_x0`, `spk_x1` | −25.7, −12.3 | |
| 13 | Bottom microphone | x of the small hole right of USB-C | `mic_bot_x` | 11.2 | 10.8–12.9 |
| 14 | Top microphone | x of the hole on the top edge | `mic_top_x` | 22.6 | 21.9–23.1 (one case: 26.4) |
| 15 | Corner radius | lay the phone on paper and trace a corner, or compare with a radius gauge | `corner_r` | 12.0 | 11.3–12.1 |

The easiest way to catch a mistake is the fit band (`out/print/test_fit_band.stl`, TPU).
It's the front 6 mm of the bumper, including the lip, corners, button openings
and ports. Push it onto the phone from the screen side and check:

- it goes on with a firm stretch and doesn't slide along the phone (fit)
- each button sits in the middle of its opening, with no rub at either end
- the USB-C, speaker and microphone holes line up with the phone's holes
- the lip covers only the black border of the screen, not the picture

Then print `out/print/test_camera.stl` (PETG, top of the plate). Lay it on the
back of the phone: the camera bar should sit centred in the collar, with
roughly 0.3 mm of gap all round.

If something is off by more than about 0.3 mm, change that parameter. If the
whole band is loose or tight, change `Case.fit` instead: about 0.05 mm per step,
where the default is 0.10.
