from __future__ import annotations

# Default keypoints for each pan direction.
# x, y are focal-point percentages (0-100) of the image; zoom is the zoom factor.
_DIRECTION_KEYPOINTS: dict[str, list[dict]] = {
    "right":    [{"x": 25, "y": 50, "zoom": 1.2}, {"x": 75, "y": 50, "zoom": 1.3}],
    "left":     [{"x": 75, "y": 50, "zoom": 1.2}, {"x": 25, "y": 50, "zoom": 1.3}],
    "up":       [{"x": 50, "y": 70, "zoom": 1.2}, {"x": 50, "y": 30, "zoom": 1.3}],
    "down":     [{"x": 50, "y": 30, "zoom": 1.2}, {"x": 50, "y": 70, "zoom": 1.3}],
    "zoom_in":  [{"x": 50, "y": 50, "zoom": 1.0}, {"x": 50, "y": 50, "zoom": 1.5}],
    "zoom_out": [{"x": 50, "y": 50, "zoom": 1.5}, {"x": 50, "y": 50, "zoom": 1.0}],
}

# Cycle used when no keypoints and no pan_direction are provided
_AUTO_CYCLE = ["right", "left", "zoom_in", "up", "down", "zoom_out", "right", "left"]


def _interp_expr(values: list[float], total_frames: int) -> str:
    """
    Build an FFmpeg arithmetic expression that linearly interpolates through
    *values* over *total_frames* frames (the zoompan 'on' variable counts frames).
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
    # 'zoom' in x/y expressions refers to the current frame's zoom value output by z_expr
    x_expr = f"iw*({_interp_expr(x_vals, total_frames)})-iw/zoom/2"
    y_expr = f"ih*({_interp_expr(y_vals, total_frames)})-ih/zoom/2"

    filter_str = (
        f"zoompan=z='{z_expr}':d={total_frames}"
        f":x='{x_expr}':y='{y_expr}':s={resolution}:fps={fps}"
    )
    return effect_name, filter_str
