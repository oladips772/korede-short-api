import os
import textwrap
from pathlib import Path


ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

STYLE_PRESETS = {
    "bold_center": (
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,0,0,1,2,0,2,10,10,30,1"
    ),
    "bottom_bar": (
        "Style: Default,Arial,18,&H00FFFFFF,&H000000FF,&H00000000,&HC0000000,"
        "-1,0,0,0,100,100,0,0,1,3,0,2,10,10,50,1"
    ),
    "minimal": (
        "Style: Default,Arial,16,&H00FFFFFF,&H000000FF,&H00000000,&H40000000,"
        "0,0,0,0,100,100,0,0,1,1,0,2,10,10,20,1"
    ),
}


def _seconds_to_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_subtitle(
    narration_text: str,
    duration: float,
    style: str = "bold_center",
    output_path: str | None = None,
) -> str:
    """
    Generate an ASS subtitle file for a scene.
    Uses sentence-level timing proportional to character count.
    Returns the file path.
    """
    style_line = STYLE_PRESETS.get(style, STYLE_PRESETS["bold_center"])
    header = ASS_HEADER.format(style_line=style_line)

    # Split into chunks of ~80 chars for readability
    chunks = _split_into_chunks(narration_text, max_chars=80)
    total_chars = sum(len(c) for c in chunks)

    events = []
    elapsed = 0.0
    for chunk in chunks:
        chunk_duration = (len(chunk) / total_chars) * duration if total_chars > 0 else duration
        start = _seconds_to_ass_time(elapsed)
        end = _seconds_to_ass_time(elapsed + chunk_duration)
        # Escape ASS special chars
        safe_text = chunk.replace("{", "\\{").replace("}", "\\}")
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{safe_text}")
        elapsed += chunk_duration

    ass_content = header + "\n".join(events) + "\n"

    if output_path is None:
        output_path = f"/tmp/subtitle_{os.getpid()}.ass"

    Path(output_path).write_text(ass_content, encoding="utf-8")
    return output_path


def _split_into_chunks(text: str, max_chars: int = 80) -> list[str]:
    """Split text into subtitle chunks, respecting sentence boundaries."""
    sentences = []
    for sent in text.replace("!", ".").replace("?", ".").split("."):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= max_chars:
            sentences.append(sent)
        else:
            # Wrap long sentences
            wrapped = textwrap.wrap(sent, width=max_chars)
            sentences.extend(wrapped)
    return sentences if sentences else [text]
