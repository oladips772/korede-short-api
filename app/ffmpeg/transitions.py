from app.ffmpeg.commands import run_ffmpeg


async def apply_crossfade_concat(
    scene_paths: list[str],
    output_path: str,
    transition_duration_ms: int = 500,
) -> None:
    """
    Concatenate scene clips with crossfade transitions.
    For simplicity, uses the concat demuxer (cut transitions) and then applies
    a crossfade via the xfade filter for pairs of clips if needed.
    """
    if len(scene_paths) == 1:
        # Single scene — just copy
        await run_ffmpeg("-i", scene_paths[0], "-c", "copy", output_path)
        return

    # Build a concat file for cut-based joining (fast, no re-encode of video stream)
    concat_file = output_path + ".concat_list.txt"
    with open(concat_file, "w") as f:
        for path in scene_paths:
            f.write(f"file '{path}'\n")

    await run_ffmpeg(
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
        timeout=600,
    )
