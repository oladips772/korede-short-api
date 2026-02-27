import random
from typing import NamedTuple

# Ken Burns effect presets (zoompan filter expressions).
# Placeholders: {duration} = total frames, {resolution} = WxH, {fps} = frame rate
KENBURNS_PRESETS: dict[str, str] = {
    "zoom_in_center": (
        "zoompan=z='min(zoom+0.0015,1.5)':d={duration}"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}"
    ),
    "zoom_out_center": (
        "zoompan=z='if(eq(on,1),1.5,max(zoom-0.0015,1.0))':d={duration}"
        ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}"
    ),
    "pan_left_to_right": (
        "zoompan=z='1.3':d={duration}"
        ":x='if(eq(on,1),0,min(x+2,(iw-iw/zoom)))':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}"
    ),
    "pan_right_to_left": (
        "zoompan=z='1.3':d={duration}"
        ":x='if(eq(on,1),(iw-iw/zoom),max(x-2,0))':y='ih/2-(ih/zoom/2)':s={resolution}:fps={fps}"
    ),
    "pan_top_to_bottom": (
        "zoompan=z='1.3':d={duration}"
        ":x='iw/2-(iw/zoom/2)':y='if(eq(on,1),0,min(y+2,(ih-ih/zoom)))':s={resolution}:fps={fps}"
    ),
    "pan_bottom_to_top": (
        "zoompan=z='1.3':d={duration}"
        ":x='iw/2-(iw/zoom/2)':y='if(eq(on,1),(ih-ih/zoom),max(y-2,0))':s={resolution}:fps={fps}"
    ),
    "zoom_in_top_left": (
        "zoompan=z='min(zoom+0.0015,1.5)':d={duration}:x='0':y='0':s={resolution}:fps={fps}"
    ),
    "zoom_in_bottom_right": (
        "zoompan=z='min(zoom+0.0015,1.5)':d={duration}"
        ":x='iw-(iw/zoom)':y='ih-(ih/zoom)':s={resolution}:fps={fps}"
    ),
    "slow_drift": (
        "zoompan=z='1.1':d={duration}"
        ":x='iw/2-(iw/zoom/2)+sin(on/50)*50':y='ih/2-(ih/zoom/2)+cos(on/50)*30':s={resolution}:fps={fps}"
    ),
}

PRESET_NAMES = list(KENBURNS_PRESETS.keys())


class KenBurnsEffect(NamedTuple):
    name: str
    filter_expr: str


def get_effect_for_scene(scene_number: int, previous_effect: str | None = None) -> KenBurnsEffect:
    """
    Return a Ken Burns effect for the scene.
    Cycles through presets in order, but ensures no two adjacent scenes use the same effect.
    """
    idx = (scene_number - 1) % len(PRESET_NAMES)
    name = PRESET_NAMES[idx]

    # Avoid repeating the same effect for consecutive scenes
    if name == previous_effect:
        idx = (idx + 1) % len(PRESET_NAMES)
        name = PRESET_NAMES[idx]

    return KenBurnsEffect(name=name, filter_expr=KENBURNS_PRESETS[name])


def build_kenburns_filter(
    scene_number: int,
    voice_duration: float,
    resolution: str,
    fps: int,
    previous_effect: str | None = None,
) -> tuple[str, str]:
    """
    Build the zoompan filter string for a Ken Burns scene.
    Returns (effect_name, filter_string).
    """
    effect = get_effect_for_scene(scene_number, previous_effect)
    total_frames = int(voice_duration * fps)

    filter_str = effect.filter_expr.format(
        duration=total_frames,
        resolution=resolution,
        fps=fps,
    )
    return effect.name, filter_str
