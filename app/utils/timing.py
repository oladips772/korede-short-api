def calculate_speed_factor(video_duration: float, voice_duration: float) -> float | None:
    """
    Calculate speed adjustment factor to match video to voice duration.

    Returns:
        float: Speed factor to apply (>1 = speed up, <1 = slow down)
        None: If the video is too short (< 50% of voice duration) — use loop strategy instead
    """
    if video_duration <= 0:
        raise ValueError("Invalid video duration")
    if voice_duration <= 0:
        raise ValueError("Invalid voice duration")

    ratio = video_duration / voice_duration

    # Video is too short — signal to use loop
    if ratio < 0.5:
        return None

    return ratio


def estimate_completion_minutes(
    remaining_scenes: int,
    channel: str,
    concurrent_workers: int = 4,
) -> float:
    """Rough estimate of remaining processing time in minutes."""
    seconds_per_scene = 10 if channel == "kenburns" else 60
    effective_rate = concurrent_workers
    return round((remaining_scenes / effective_rate) * seconds_per_scene / 60, 1)
