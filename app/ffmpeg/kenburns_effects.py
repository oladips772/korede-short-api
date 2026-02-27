from __future__ import annotations

# Default keypoints for each pan direction.
# x, y are focal-point percentages (0-100) of the image; zoom is the zoom factor.
#
# GEOMETRY CONSTRAINT: at a given zoom z, the top-left corner of the crop window
# in input coordinates is:
#   x_tl = iw * (x_pct/100) - iw / (2*z)
# For x_tl to be valid: 0 <= x_tl <= iw - iw/z  =>  1/(2z) <= x_pct <= 1 - 1/(2z)
#
# At zoom=1.5: valid x range ≈ [33.3%, 66.7%]
# At zoom=1.8: valid x range ≈ [27.8%, 72.2%]
# At zoom=2.0: valid x range ≈ [25.0%, 75.0%]
# All default keypoints below are chosen to stay within these bounds.

_DIRECTION_KEYPOINTS: dict[str, list[dict]] = {
    "right":    [{"x": 36, "y": 50, "zoom": 1.5}, {"x": 64, "y": 50, "zoom": 1.5}],
    "left":     [{"x": 64, "y": 50, "zoom": 1.5}, {"x": 36, "y": 50, "zoom": 1.5}],
    "up":       [{"x": 50, "y": 64, "zoom": 1.5}, {"x": 50, "y": 36, "zoom": 1.5}],
    "down":     [{"x": 50, "y": 36, "zoom": 1.5}, {"x": 50, "y": 64, "zoom": 1.5}],
    "zoom_in":  [{"x": 50, "y": 50, "zoom": 1.0}, {"x": 50, "y": 50, "zoom": 1.8}],
    "zoom_out": [{"x": 50, "y": 50, "zoom": 1.8}, {"x": 50, "y": 50, "zoom": 1.0}],
}

# Cycle used when no keypoints and no pan_direction are provided
_AUTO_CYCLE = ["zoom_in", "right", "left", "zoom_out", "up", "down", "zoom_in", "right"]


def _interp_expr(values: list[float], total_frames: int) -> str:
    """
    Build an FFmpeg arithmetic expression that linearly interpolates through
    *values* over *total_frames* frames.  The zoompan filter variable 'on'
    counts output frames starting at 1.
    """
    n = len(values)
    if n == 1:
        return f"{values[0]:.6f}"

    if n == 2:
        v0, v1 = values[0], values[1]
        return f"{v0:.6f}+{(v1 - v0):.6f}*on/{total_frames}"

    seg = total_frames / (n - 1)

    def _seg(i: int) -> str:
        v0, v1 = values[i], values[i + 1]
        start = i * seg
        return f"{v0:.6f}+{(v1 - v0):.6f}*(on-{start:.2f})/{seg:.2f}"

    # Build right-to-left nested if() chain
    expr = _seg(n - 2)
    for i in range(n - 3, -1, -1):
        threshold = (i + 1) * seg
        expr = f"if(lte(on,{threshold:.2f}),{_seg(i)},{expr})"
    return expr


def build_kenburns_filter(
    scene_number: int,
    voice_duration: float,
    resolution: str,
    fps: int,
    keypoints: list[dict] | None = None,
    pan_direction: str | None = None,
) -> tuple[str, str]:
    """
    Build a zoompan filter string for a Ken Burns scene.
    Returns (effect_name, filter_string).

    Priority:
      1. Explicit keypoints  — [{x: 0-100, y: 0-100, zoom: float}, ...]
      2. pan_direction       — "right" | "left" | "up" | "down" | "zoom_in" | "zoom_out"
      3. Auto-cycle          — derived from scene_number

    The filter_string is meant to be prepended by "scale=8000:-2," in the caller
    so that zoompan operates on a high-resolution input (smooth motion).
    'iw' and 'ih' inside the expressions will therefore refer to the 8000-px scaled
    image, not the original — but since we work in percentages the math is identical.
    """
    total_frames = max(1, int(voice_duration * fps))

    if keypoints and len(keypoints) >= 2:
        kps = keypoints
        effect_name = "custom_keypoints"
    else:
        direction = (
            pan_direction
            if pan_direction in _DIRECTION_KEYPOINTS
            else _AUTO_CYCLE[(scene_number - 1) % len(_AUTO_CYCLE)]
        )
        kps = _DIRECTION_KEYPOINTS[direction]
        effect_name = direction

    x_vals = [kp["x"] / 100.0 for kp in kps]
    y_vals = [kp["y"] / 100.0 for kp in kps]
    z_vals = [float(kp["zoom"]) for kp in kps]

    z_expr = _interp_expr(z_vals, total_frames)

    # Raw focal-point position (top-left of crop window in input coordinates).
    # 'zoom' refers to the current frame's zoom value produced by z_expr.
    x_raw = f"iw*({_interp_expr(x_vals, total_frames)})-iw/zoom/2"
    y_raw = f"ih*({_interp_expr(y_vals, total_frames)})-ih/zoom/2"

    # Clamp so the crop window never exceeds the image boundaries.
    # Without clamping, negative x/y values cause corrupted or black-bordered output.
    x_expr = f"max(0,min({x_raw},iw-iw/zoom))"
    y_expr = f"max(0,min({y_raw},ih-ih/zoom))"

    filter_str = (
        f"zoompan=z='{z_expr}':d={total_frames}"
        f":x='{x_expr}':y='{y_expr}':s={resolution}:fps={fps}"
    )
    return effect_name, filter_str
