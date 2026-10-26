"""Japanese narration defaults and stricter stock-footage selection."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode, VideoParams
from app.services import japanese_support, llm, material, video
from app.services.video import SubClippedVideoClip


ROOT = Path(__file__).parent.parent.parent
FONT = ROOT / "resource" / "fonts" / "NotoSansJP-Bold.ttf"


def _clip(source: str, duration: float) -> SubClippedVideoClip:
    return SubClippedVideoClip(
        file_path=source,
        duration=duration,
        source_file_path=source,
    )


def test_english_request_keeps_builtin_voice_and_font():
    params = VideoParams(
        video_subject="Morning coffee",
        video_script="A quiet cup of coffee.",
        video_language="en-US",
        voice_name="zh-CN-XiaoxiaoNeural-Female",
    )
    japanese_support.apply_japanese_narration_defaults(params)
    assert params.voice_name == "zh-CN-XiaoxiaoNeural-Female"
    assert params.font_name == "STHeitiMedium.ttc"


def test_japanese_language_replaces_only_default_voice_and_font():
    params = VideoParams(
        video_subject="静かな朝",
        video_language="ja-JP",
        voice_name="",
    )
    japanese_support.apply_japanese_narration_defaults(params)
    assert params.voice_name == "ja-JP-NanamiNeural-Female"
    assert params.font_name == "NotoSansJP-Bold.ttf"

    explicit = VideoParams(
        video_subject="静かな朝",
        video_language="ja-JP",
        voice_name="en-US-JennyNeural-Female",
        font_name="Charm-Bold.ttf",
    )
    japanese_support.apply_japanese_narration_defaults(explicit)
    assert explicit.voice_name == "en-US-JennyNeural-Female"
    assert explicit.font_name == "Charm-Bold.ttf"


def test_explicit_english_language_is_not_inferred_from_a_japanese_quote():
    params = VideoParams(
        video_subject="Travel notes",
        video_script="She said おはよう once.",
        video_language="en-US",
        voice_name="",
    )
    japanese_support.apply_japanese_narration_defaults(params)
    assert params.voice_name == ""
    assert params.font_name == "STHeitiMedium.ttc"


def test_empty_language_with_kana_uses_japanese_defaults():
    params = VideoParams(video_subject="朝の散歩", voice_name="zh-CN-XiaoxiaoNeural")
    japanese_support.apply_japanese_narration_defaults(params)
    assert params.voice_name == "ja-JP-NanamiNeural-Female"
    assert params.font_name == "NotoSansJP-Bold.ttf"


def test_cli_japanese_language_uses_configured_voice_without_changing_english_default():
    import cli
    from app.config import config

    with patch.dict(config.ui, {}, clear=True):
        english = cli.build_video_params(
            cli.parse_args(["--video-subject", "test"])
        )
        japanese = cli.build_video_params(
            cli.parse_args(
                ["--video-subject", "静かな朝", "--video-language", "ja-JP"]
            )
        )
        explicit = cli.build_video_params(
            cli.parse_args(
                [
                    "--video-subject",
                    "静かな朝",
                    "--video-language",
                    "ja-JP",
                    "--voice-name",
                    "en-US-JennyNeural-Female",
                ]
            )
        )
    assert english.voice_name == "zh-CN-XiaoxiaoNeural-Female"
    assert japanese.voice_name == "ja-JP-NanamiNeural-Female"
    assert explicit.voice_name == "en-US-JennyNeural-Female"


def test_api_model_defaults_stay_compatible():
    params = VideoParams(video_subject="Coffee")
    assert params.video_language == ""
    assert params.voice_name == ""
    assert params.font_name == "STHeitiMedium.ttc"
    assert params.video_aspect == "9:16"
    assert params.video_source == "pexels"


def test_japanese_terms_are_translated_and_english_terms_are_not(monkeypatch):
    generate = Mock(return_value='["morning coffee", "quiet street"]')
    monkeypatch.setattr(llm, "_generate_response", generate)
    translated = llm.ensure_english_stock_terms(
        ["朝のコーヒー", "静かな通り"],
        video_subject="朝のコーヒー",
        video_script="湯気の立つコーヒー。",
        language="ja-JP",
    )
    assert translated == ["morning coffee", "quiet street"]
    assert generate.call_count == 1

    generate.reset_mock()
    unchanged = llm.ensure_english_stock_terms(
        ["morning coffee"],
        video_subject="Coffee",
        video_script="A quiet cup.",
        language="en-US",
    )
    assert unchanged == ["morning coffee"]
    assert generate.call_count == 0


def test_generate_terms_prompt_asks_for_concrete_english_keywords(monkeypatch):
    captured = {}

    def fake_generate(prompt):
        captured["prompt"] = prompt
        return '["morning coffee"]'

    monkeypatch.setattr(llm, "_generate_response", fake_generate)
    assert llm.generate_terms("静かな朝", "コーヒーを淹れる。", amount=1) == [
        "morning coffee"
    ]
    assert "concrete English keywords" in captured["prompt"]
    assert "Japanese, Chinese, and other languages are not accepted" in captured["prompt"]


def test_pixabay_drops_unrelated_tags_and_keeps_untagged_hits():
    response = SimpleNamespace(
        status_code=200,
        headers={"content-type": "application/json"},
        json=lambda: {
            "hits": [
                {
                    "id": 1,
                    "duration": 8,
                    "tags": "neon, city, night, lights",
                    "videos": {
                        "large": {
                            "width": 1080,
                            "height": 1920,
                            "url": "https://example.com/neon.mp4",
                        }
                    },
                },
                {
                    "id": 2,
                    "duration": 8,
                    "tags": "coffee, cup, kitchen, morning",
                    "videos": {
                        "large": {
                            "width": 1080,
                            "height": 1920,
                            "url": "https://example.com/coffee.mp4",
                        }
                    },
                },
                {
                    "id": 3,
                    "duration": 8,
                    "videos": {
                        "large": {
                            "width": 1080,
                            "height": 1920,
                            "url": "https://example.com/untagged.mp4",
                        }
                    },
                },
            ]
        },
    )
    with (
        patch.object(material, "get_api_key", return_value="fixture-key"),
        patch.object(material.requests, "get", return_value=response),
    ):
        results = material.search_videos_pixabay(
            "morning coffee", 1, VideoAspect.portrait
        )
    assert [item.url for item in results] == [
        "https://example.com/coffee.mp4",
        "https://example.com/untagged.mp4",
    ]


def test_landscape_fallback_runs_only_when_portrait_coverage_is_short(monkeypatch):
    portrait = MaterialInfo(
        provider="pixabay",
        url="https://example.com/portrait.mp4",
        duration=4,
        source_info={"rendition": {"width": 1080, "height": 1920}},
    )
    landscape = MaterialInfo(
        provider="pixabay",
        url="https://example.com/landscape.mp4",
        duration=20,
        source_info={"rendition": {"width": 1920, "height": 1080}},
    )

    def search(search_term, minimum_duration, video_aspect):
        if VideoAspect(video_aspect) == VideoAspect.portrait:
            return [portrait]
        return [landscape]

    saved = []

    def save_video(video_url, save_dir=""):
        saved.append(video_url)
        return f"/tmp/{video_url.rsplit('/', 1)[-1]}"

    monkeypatch.setattr(material, "search_videos_pixabay", search)
    monkeypatch.setattr(material, "save_video", save_video)
    monkeypatch.setattr(material.material_cache, "load_material_search_cache", lambda **kwargs: None)
    monkeypatch.setattr(material.material_cache, "save_material_search_cache", lambda **kwargs: None)
    monkeypatch.setattr(material.task_artifacts, "patch_script_data", lambda *args, **kwargs: True)

    result = material.download_videos(
        task_id="fallback",
        search_terms=["morning coffee"],
        source="pixabay",
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        audio_duration=30,
        max_clip_duration=5,
    )
    assert saved == [
        "https://example.com/portrait.mp4",
        "https://example.com/landscape.mp4",
    ]
    assert result == ["/tmp/portrait.mp4", "/tmp/landscape.mp4"]

    saved.clear()
    covered = material.download_videos(
        task_id="enough",
        search_terms=["morning coffee"],
        source="pixabay",
        video_aspect=VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.sequential,
        audio_duration=4,
        max_clip_duration=5,
    )
    assert saved == ["https://example.com/portrait.mp4"]
    assert covered == ["/tmp/portrait.mp4"]


def test_single_source_stops_instead_of_looping_for_the_whole_video():
    with pytest.raises(RuntimeError, match="Refusing to loop a single clip"):
        video.extend_clip_sequence([_clip("only.mp4", 5)], 5, 60, max_single_source_plays=3)


def test_single_short_clip_can_repeat_a_limited_number_of_times():
    clips, duration = video.extend_clip_sequence(
        [_clip("short.mp4", 0.4)], 0.4, 1.0, max_single_source_plays=3
    )
    assert len(clips) == 3
    assert duration == pytest.approx(1.2)


def test_repeated_sources_are_not_placed_back_to_back():
    clips, duration = video.extend_clip_sequence(
        [_clip("a.mp4", 2), _clip("b.mp4", 2)],
        4,
        10,
        max_single_source_plays=3,
    )
    assert duration >= 10
    sources = [clip.source_file_path for clip in clips]
    assert all(left != right for left, right in zip(sources, sources[1:]))


def test_japanese_wrap_prefers_punctuation_and_avoids_forbidden_line_starts():
    text = "朝の光が部屋に入る。静かなコーヒーが湯気を立てている。"
    wrapped, _height = video.wrap_text(
        text,
        max_width=280,
        font=str(FONT),
        fontsize=48,
    )
    lines = wrapped.split("\n")
    assert len(lines) > 1
    assert any(line.endswith("。") for line in lines)
    forbidden = set("。、「」っゃゅょ")
    assert all(line[0] not in forbidden for line in lines)
    assert "\n。" not in wrapped
    assert "".join(lines) == text


def test_webui_lists_japanese_script_language():
    module = ast.parse((ROOT / "webui" / "Main.py").read_text(encoding="utf-8"))
    support_locales = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "support_locales":
                support_locales = ast.literal_eval(node.value)
    assert support_locales is not None
    assert "ja-JP" in support_locales


def _selectbox(app, key):
    return next(
        item
        for item in app.selectbox
        if item.key == key or str(item.key).startswith(f"{key}_")
    )


def test_webui_japanese_script_language_selects_voice_and_font():
    """Changing the script language to Japanese updates the Edge voice and font."""
    from streamlit.testing.v1 import AppTest

    from app.config import config
    from app.services import state as sm
    from app.services import version_checker

    with (
        patch.object(
            config,
            "app",
            {"llm_provider": "openai", "video_source": "pexels"},
        ),
        patch.object(
            config,
            "ui",
            {
                "language": "en",
                "voice_mode": "tts",
                "tts_server": "azure-tts-v1",
                "voice_name": "zh-CN-XiaoxiaoNeural-Female",
                "video_language": "",
                "font_name": "MicrosoftYaHeiBold.ttc",
            },
        ),
        patch.object(config, "try_save_config", return_value=True),
        patch.object(sm.state, "get_all_tasks", return_value=([], 0)),
        patch.object(
            version_checker,
            "poll_available_update",
            return_value=version_checker.UpdateCheckSnapshot(complete=True),
        ),
    ):
        app = AppTest.from_file(str(ROOT / "webui" / "Main.py"), default_timeout=60)
        app.session_state["ui_language"] = "en"
        app.run()
        assert not app.exception

        language = _selectbox(app, "script_language_select")
        assert "ja-JP" in list(language.options)
        assert language.value == ""
        assert (
            _selectbox(app, "speech_synthesis_select_azure-tts-v1").value
            == "zh-CN-XiaoxiaoNeural-Female"
        )
        assert _selectbox(app, "font_name_select").value == "MicrosoftYaHeiBold.ttc"

        language.set_value("ja-JP").run()
        assert not app.exception
        assert _selectbox(app, "script_language_select").value == "ja-JP"
        assert (
            _selectbox(app, "speech_synthesis_select_azure-tts-v1").value
            == "ja-JP-NanamiNeural-Female"
        )
        assert _selectbox(app, "font_name_select").value == "NotoSansJP-Bold.ttf"
