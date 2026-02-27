from app.ffmpeg.kenburns_effects import build_kenburns_filter, PRESET_NAMES


def test_kenburns_filter_returns_valid_preset():
    name, filter_str = build_kenburns_filter(
        scene_number=1,
        voice_duration=5.0,
        resolution="1080x1920",
        fps=30,
    )
    assert name in PRESET_NAMES
    assert "zoompan" in filter_str
    assert "d=150" in filter_str  # 5.0 * 30 = 150 frames


def test_kenburns_avoids_repeating_effect():
    _, filter1 = build_kenburns_filter(1, 5.0, "1080x1920", 30, previous_effect=None)
    name1, _ = build_kenburns_filter(1, 5.0, "1080x1920", 30)
    name2, _ = build_kenburns_filter(2, 5.0, "1080x1920", 30, previous_effect=name1)
    assert name1 != name2


def test_all_presets_have_required_placeholders():
    from app.ffmpeg.kenburns_effects import KENBURNS_PRESETS
    for name, template in KENBURNS_PRESETS.items():
        formatted = template.format(duration=150, resolution="1080x1920", fps=30)
        assert "zoompan" in formatted
