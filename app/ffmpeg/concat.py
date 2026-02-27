from app.ffmpeg.commands import run_ffmpeg


async def concat_videos(scene_paths: list[str], output_path: str) -> None:
    """Simple concat using the concat demuxer. All inputs must share the same codec."""
    concat_file = output_path + ".txt"
    with open(concat_file, "w") as f:
        for p in scene_paths:
            f.write(f"file '{p}'\n")

    await run_ffmpeg(
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        output_path,
        timeout=600,
    )
