import os
import tempfile
from app.ffmpeg.subtitles import generate_ass_subtitle


def test_generate_ass_subtitle_creates_file():
    text = "In the year 2045, the world had changed. Nobody expected this."
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
        path = f.name
    try:
        result = generate_ass_subtitle(text, duration=6.0, style="bold_center", output_path=path)
        assert os.path.exists(result)
        content = open(result).read()
        assert "[Script Info]" in content
        assert "[Events]" in content
        assert "Dialogue:" in content
    finally:
        os.unlink(path)


def test_subtitle_timing_covers_duration():
    text = "Short text."
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as f:
        path = f.name
    try:
        generate_ass_subtitle(text, duration=3.0, output_path=path)
        content = open(path).read()
        assert "0:00:03" in content or "0:00:02" in content  # ends near 3s
    finally:
        os.unlink(path)
