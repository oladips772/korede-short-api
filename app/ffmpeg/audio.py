from app.ffmpeg.commands import run_ffmpeg, get_video_duration


async def normalize_audio(input_path: str, output_path: str) -> None:
    """Apply loudnorm filter for consistent audio levels."""
    await run_ffmpeg(
        "-i", input_path,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:v", "copy",
        output_path,
    )


async def mix_background_music(
    video_path: str,
    music_path: str,
    output_path: str,
    music_volume: float = 0.15,
) -> None:
    """
    Mix background music under the video's narration audio.

    - Uses -stream_loop -1 to loop the music file infinitely
    - amix duration=first cuts the music exactly at the video length
    - afade=t=out fades the music out over the last 3 seconds
    - Volume is ducked to music_volume under the narration
    """
    video_duration = await get_video_duration(video_path)
    fade_start = max(0.0, video_duration - 3.0)

    filter_complex = (
        f"[1:a]volume={music_volume},afade=t=out:st={fade_start:.3f}:d=3[music];"
        "[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[aout]"
    )
    await run_ffmpeg(
        "-i", video_path,
        "-stream_loop", "-1",
        "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        output_path,
        timeout=600,
    )
