import os
from app.ffmpeg.commands import run_ffmpeg

# Shared quality flags — must match scene_assembler.py so the concat demuxer
# sees bit-for-bit compatible streams from every input file.
_VIDEO_FLAGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
_AUDIO_FLAGS = ["-c:a", "aac", "-b:a", "192k"]
_FASTSTART   = ["-movflags", "+faststart"]


async def apply_crossfade_concat(
    scene_paths: list[str],
    output_path: str,
    transition_duration_ms: int = 500,
) -> None:
    """
    Concatenate scene clips into one video using the concat demuxer.

    All scene files must already be encoded with the same codec, pixel
    format, and resolution (guaranteed by scene_assembler.py).  We
    re-encode here anyway so the output file has a clean moov atom and
    -pix_fmt yuv420p is enforced — this prevents green frames or silent
    muxing errors that occur when a scene file has a slightly different
    internal format.

    transition_duration_ms is accepted for API compatibility but is not
    used (hard-cut only).  True crossfade requires a complex xfade
    filter graph and is not implemented.
    """
    if len(scene_paths) == 1:
        # Single scene — re-encode to normalise format and add faststart.
        await run_ffmpeg(
            "-i", scene_paths[0],
            *_VIDEO_FLAGS,
            *_AUDIO_FLAGS,
            *_FASTSTART,
            output_path,
            timeout=300,
        )
        return

    concat_list = output_path + ".concat_list.txt"
    with open(concat_list, "w") as f:
        for path in scene_paths:
            # Escape single quotes in path for the concat list format.
            safe_path = path.replace("'", r"'\''")
            f.write(f"file '{safe_path}'\n")

    try:
        await run_ffmpeg(
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            *_VIDEO_FLAGS,
            *_AUDIO_FLAGS,
            *_FASTSTART,
            output_path,
            timeout=600,
        )
    finally:
        if os.path.exists(concat_list):
            os.remove(concat_list)
