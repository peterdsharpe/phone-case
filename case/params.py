"""Every dimension of the phone and the case, in millimetres.

Coordinate frame (used by every module):
    origin  = centre of the phone in plan view, on the back glass
    +x      = right edge as seen from the screen (power/volume side)
    +y      = top edge (camera end)
    +z      = out of the screen; back glass at z = 0, screen at z = Phone.T

Phone values marked "verify" are consensus estimates from published cases and
Google's spec sheet; measure them with calipers once the phone arrives
(see MEASURE.md) and edit them here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Phone:
    """Google Pixel 9 Pro XL."""

    W: float = 76.6  # width, Google spec
    L: float = 162.8  # height, Google spec
    T: float = 8.5  # thickness without the camera bar, Google spec
    corner_r: float = 12.0  # plan-view corner radius. verify: refs say 11.3-12.1
    edge_r: float = 1.0  # rounding where the glass meets the frame. verify: refs 0.5-1.2

    # Camera bar: a stadium (pill) on the back, centred left-right.
    cam_len: float = 70.6  # verify: refs 69.2-70.6
    cam_h: float = 22.6  # verify: refs 21.75-22.6
    cam_top: float = 13.15  # gap from the phone's top edge to the bar. verify: refs 13.0-13.6
    cam_proud: float = 3.6  # bar height above the back glass. verify: refs 3.5-3.6

    # Right-side buttons, distances from the top edge (centred in thickness).
    power_top: float = 43.4  # verify
    power_len: float = 12.0  # verify
    vol_top: float = 62.2  # verify
    vol_len: float = 22.0  # verify
    btn_h: float = 3.0  # button size across the phone's thickness
    btn_proud: float = 0.6  # how far the buttons stick out of the frame

    # Bottom edge (x measured from the centre, seen from the screen).
    usb_w: float = 8.4
    usb_h: float = 2.6
    spk_x0: float = -25.7  # speaker grille, left end. verify
    spk_x1: float = -12.3  # speaker grille, right end. verify
    mic_bot_x: float = 11.2  # verify
    # Top edge.
    mic_top_x: float = 22.6  # verify: refs 21.9-23.1 (one outlier at 26.4)

    @property
    def cam_y(self) -> float:
        """y of the camera bar's centre."""
        return self.L / 2 - self.cam_top - self.cam_h / 2

    def from_top(self, d: float) -> float:
        """Convert a distance below the top edge into a y coordinate."""
        return self.L / 2 - d


@dataclass(frozen=True)
class Case:
    """Two-part case: a TPU bumper that holds a rigid back plate against the phone."""

    # --- fit -------------------------------------------------------------------
    fit: float = 0.10  # side clearance, phone to bumper. TPU refs use 0 to 0.2
    fit_z: float = 0.0  # thickness clearance, plate + phone inside the bumper (TPU stretches)

    # --- bumper walls and corners ---------------------------------------------
    wall: float = 1.4  # side wall: two 0.7 mm perimeters from a 0.6 mm nozzle
    outer_corner_r: float = 8.0  # smaller than the phone's 12 mm -> thicker corners
    corner_relief_r: float = 9.0  # inner corner pocket -> ~1.3 mm air gap at each corner
    corner_relief_margin: float = 1.0  # pocket stops this far from the front/back faces
    front_chamfer: float = 0.5  # outer edge on the bed when printing
    back_fillet: float = 0.8

    # --- front lip -------------------------------------------------------------
    lip_h: float = 1.4  # lip height above the screen glass (all round)
    lip_side: float = 1.2  # how far the lip reaches over the screen, long sides (refs: 1.3-1.5)
    lip_end: float = 1.4  # ... top and bottom
    lip_side_inner_h: float = 0.5  # side lips bevel down to this at their inner edge
    lip_end_bevel: float = 0.4  # top/bottom lips: small chamfer only

    # --- back plate and the bumper flange that retains it ----------------------
    plate_t: float = 1.25  # plate thickness under the relief (0.2 first layer + 7 x 0.15)
    plate_inset: float = 0.25  # plate outline is this much inside the phone outline
    plate_bevel: float = 1.0  # 45-degree bevel on the plate's outer edge
    plate_gap: float = 0.10  # clearance plate to bumper
    flange_proud: float = 0.6  # TPU rim stands this far above the plate's face
    flange_extra: float = 0.3  # rim reaches this far past the bevel onto the plate

    # --- camera collar (part of the plate) ---------------------------------------
    collar_clear: float = 0.3  # gap around the camera bar
    collar_wall: float = 1.5
    collar_guard: float = 1.0  # collar stands this far above the camera glass
    collar_chamfer: float = 0.6  # inner top bevel, keeps flash glare off the lenses
    collar_fillet: float = 0.4  # outer top edge

    # --- cut-outs -----------------------------------------------------------------
    btn_margin: float = 1.5  # opening extends past each end of a button
    btn_cut_h: float = 5.5  # opening size across the thickness
    vol_post: float = 2.5  # bar splitting the volume opening (shorter TPU bridges)
    cut_flare: float = 0.6  # openings widen by this much at the outer surface
    usb_cut_w: float = 13.4
    usb_cut_h: float = 6.4
    spk_margin: float = 1.0
    spk_cut_h: float = 3.0
    mic_cut_w: float = 3.6
    mic_cut_h: float = 2.4

    # --- grip flutes on the long sides ---------------------------------------------
    grip: bool = True
    grip_depth: float = 0.3
    grip_r: float = 0.55  # flute radius (width ~1 mm at 0.3 mm depth)
    grip_pitch: float = 2.4
    grip_left_y: tuple[float, float] = (-62.0, 34.0)
    grip_right_y: tuple[float, float] = (-62.0, -9.0)

    # --- relief on the plate ----------------------------------------------------------
    # "streamlines" (toolpaths along the collar's wake, spliced into the G-code),
    # "karman" (raised vortex-street streaklines), "topo" (terraced map), or "none"
    design: str = "streamlines"
    plate_layer: float = 0.15  # plate print layer height; relief heights are multiples of it
    relief_margin: float = 0.4  # keep relief this far inside the rim
    relief_collar_margin: float = 1.2  # ...and this far from the camera collar
    # Kármán street (see case/flow.py for the simulation parameters)
    flow_ridge_w: float = 1.0  # dye line width
    flow_ridge_h: float = 0.45  # dye line height (3 layers)
    flow_cyl_h: float = 0.45  # the cylinder stands this much above the dye lines
    # Streamline top layer (see case/lbm.py for the flow, case/toolpath.py for the G-code)
    stream_source: str = "dye"  # "dye": contours of the dye label (streaklines); "streamlines": instantaneous
    dye_smooth: float = 1.2  # smooth the dye label at this scale (mm) before contouring: the print's resolution
    stream_h: float = 0.25  # the streamline layer's height (thicker = richer colour)
    stream_sep: float = 0.55  # line spacing; 0.6 mm wide lines at 0.25 mm layers
    stream_phase: int = 4  # which of the 16 snapshots over one shedding period
    stream_bands: int = 12  # colour pieces in the cut list (equal stream-function ranges)
    base_layer: float = 0.25  # plate layers under the streamline layer (hidden, so thick)
    # Terraced topographic map
    topo_source: str = "rainier"  # a key of topo.PLACES, "lat,lon,width_km", or "procedural:<seed>"
    topo_levels: int = 6  # number of terraces
    topo_step: float = 0.15  # terrace height = one 0.15 mm layer
    min_feature: float = 0.8  # drop islands/slivers narrower than this (0.6 nozzle)
    two_color_level: int = 1  # two-colour plate: filament swap at the start of this relief layer

    # Derived sizes ------------------------------------------------------------------
    def outer_W(self, p: Phone) -> float:
        return p.W + 2 * (self.fit + self.wall)

    def outer_L(self, p: Phone) -> float:
        return p.L + 2 * (self.fit + self.wall)

    @property
    def z_back(self) -> float:
        """Back face of the bumper rim (most negative z of the bumper)."""
        return -(self.plate_t + self.flange_proud)

    def z_front(self, p: Phone) -> float:
        """Front face of the lip."""
        return p.T + self.lip_h

    def collar_top(self, p: Phone) -> float:
        return -(p.cam_proud + self.collar_guard)

    @property
    def flange_reach(self) -> float:
        """Rim reaches this far inside the phone outline."""
        return self.plate_inset + self.plate_bevel + self.flange_extra


PHONE = Phone()
CASE = Case()


def variant(**changes) -> Case:
    """A modified copy of the default case, e.g. variant(fit=0.2)."""
    return replace(CASE, **changes)
