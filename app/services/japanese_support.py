"""Japanese narration defaults and stock-footage helpers.

Other languages keep their existing voice, font, and search behavior. These
helpers only change a request when the narration is Japanese and the voice or
font is still one of the built-in defaults.
"""

from __future__ import annotations

import os
import re

from loguru import logger

from app.config import config

JAPANESE_VOICE_NAME = "ja-JP-NanamiNeural-Female"
JAPANESE_FONT_NAME = "NotoSansJP-Bold.ttf"
DEFAULT_REPLACE_VOICES = (
    "",
    "zh-CN-XiaoxiaoNeural-Female",
    "zh-CN-XiaoxiaoNeural",
)
DEFAULT_REPLACE_FONTS = (
    "STHeitiMedium.ttc",
    "MicrosoftYaHeiBold.ttc",
)
DEFAULT_FALLBACK_SOURCES = ("pexels", "pixabay", "coverr")
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9d]")
_CJK_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u9fff\uff66-\uff9d]")
_JAPANESE_LANGUAGE_ALIASES = {
    "ja",
    "jp",
    "jpn",
    "ja-jp",
    "japanese",
    "日本語",
}


def _app_value(key: str, default):
    return config.app.get(key, default)


def _app_bool(key: str, default: bool) -> bool:
    value = _app_value(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(default)


def _app_int(key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_app_value(key, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _app_str_list(key: str, default: tuple[str, ...]) -> list[str]:
    value = config.app.get(key, None)
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",")]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value]
    return list(default)


def is_japanese_language(language: str | None) -> bool:
    """True for ja, ja-JP, and the Japanese language name."""
    value = str(language or "").strip().lower().replace("_", "-")
    if not value:
        return False
    return value in _JAPANESE_LANGUAGE_ALIASES or value.startswith("ja-")


def contains_japanese_kana(text: str | None) -> bool:
    return bool(_KANA_RE.search(str(text or "")))


def term_has_cjk(text: str | None) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def narration_is_japanese(language: str | None, *texts: str | None) -> bool:
    """Japanese when the language is Japanese.

    An empty language follows the subject or script, but only when kana is
    present. An explicit non-Japanese language stays on its existing path even
    if the text quotes a Japanese word.
    """
    if is_japanese_language(language):
        return True
    if str(language or "").strip():
        return False
    return any(contains_japanese_kana(text) for text in texts)


def configured_japanese_voice() -> str:
    voice = str(_app_value("japanese_voice_name", JAPANESE_VOICE_NAME) or "").strip()
    return voice or JAPANESE_VOICE_NAME


def configured_japanese_font() -> str:
    font = str(_app_value("japanese_font_name", JAPANESE_FONT_NAME) or "").strip()
    return font or JAPANESE_FONT_NAME


def default_voice_for_language(language: str | None) -> str:
    """CLI fallback when neither the command nor the UI saved a voice."""
    if is_japanese_language(language):
        return configured_japanese_voice()
    return ""


def font_file_exists(font_name: str | None) -> bool:
    name = str(font_name or "").strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    from app.utils import utils

    return os.path.isfile(os.path.join(utils.font_dir(), name))


def _normalized_voice(voice_name: str | None) -> str:
    voice = str(voice_name or "").strip()
    if ":" in voice:
        return voice
    return voice.removesuffix("-Female").removesuffix("-Male")


def voice_is_replaceable(voice_name: str | None) -> bool:
    raw = str(voice_name or "").strip()
    aliases = set(_app_str_list("japanese_replace_voices", DEFAULT_REPLACE_VOICES))
    if raw in aliases:
        return True
    return _normalized_voice(raw) in aliases


def font_is_replaceable(font_name: str | None) -> bool:
    font = str(font_name or "").strip()
    return font in set(_app_str_list("japanese_replace_fonts", DEFAULT_REPLACE_FONTS))


def apply_japanese_narration_defaults(params, script: str = "") -> None:
    """Fill Japanese voice and font when the request left the built-in defaults."""
    subject = str(getattr(params, "video_subject", "") or "")
    script_text = script or str(getattr(params, "video_script", "") or "")
    language = str(getattr(params, "video_language", "") or "")
    if not narration_is_japanese(language, subject, script_text):
        return

    if voice_is_replaceable(getattr(params, "voice_name", "")):
        voice_name = configured_japanese_voice()
        params.voice_name = voice_name
        logger.info(f"using Japanese narration voice: {voice_name}")

    current_font = str(getattr(params, "font_name", "") or "")
    if not font_is_replaceable(current_font):
        return
    font_name = configured_japanese_font()
    if font_file_exists(font_name):
        params.font_name = font_name
        logger.info(f"using Japanese subtitle font: {font_name}")
        return
    logger.warning(
        "Japanese subtitle font is missing from resource/fonts: "
        f"{font_name}. Keeping {current_font or 'the current font'}."
    )


def translate_japanese_search_terms_enabled() -> bool:
    return _app_bool("translate_japanese_search_terms", True)


def pixabay_require_tag_overlap() -> bool:
    return _app_bool("pixabay_require_tag_overlap", True)


def stock_portrait_landscape_fallback_enabled(source: str | None) -> bool:
    if not _app_bool("stock_portrait_landscape_fallback", True):
        return False
    allowed = set(
        _app_str_list("stock_landscape_fallback_sources", DEFAULT_FALLBACK_SOURCES)
    )
    return str(source or "").strip() in allowed


def stock_min_distinct_clips() -> int:
    return _app_int("stock_min_distinct_clips", 3, 1, 12)


def stock_max_single_source_plays() -> int:
    return _app_int("stock_max_single_source_plays", 3, 1, 20)
