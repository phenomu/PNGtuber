import json

import pytest

from hakuze_pngtuber.core.settings_manager import SettingsError, SettingsManager

DEFAULTS = {
    "avatar": {"scale": 0.55, "pos_x": 120, "pos_y": 120, "grayscale_intensity": 0.85,
               "idle_image": "", "talking_image": ""},
    "audio": {"rms_threshold": 0.02, "silence_ms": 300, "device_index": None},
    "animation": {"enabled": True, "talking_lift_px": 10, "breathing": False},
    "overlay": {"always_on_top": True},
    "app": {"minimize_to_tray": True},
}


@pytest.fixture()
def defaults_file(tmp_path):
    p = tmp_path / "default_settings.json"
    p.write_text(json.dumps(DEFAULTS), encoding="utf-8")
    return p


@pytest.fixture()
def user_file(tmp_path):
    return tmp_path / "settings.json"


class TestSettingsManager:
    def test_load_defaults(self, defaults_file, user_file):
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("avatar.scale") == 0.55
        assert sm.get("animation.breathing") is False

    def test_missing_user_file_uses_defaults(self, defaults_file, user_file):
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("overlay.always_on_top") is True

    def test_deep_merge(self, defaults_file, user_file):
        user_file.write_text(json.dumps({"avatar": {"scale": 0.9}}), encoding="utf-8")
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("avatar.scale") == 0.9
        assert sm.get("avatar.pos_x") == 120  # untouched sibling survives

    def test_save_load_roundtrip(self, defaults_file, user_file):
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        sm.set("avatar.scale", 1.2)
        sm.set("audio.rms_threshold", 0.03)
        sm.save()
        sm2 = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm2.get("avatar.scale") == 1.2
        assert sm2.get("audio.rms_threshold") == 0.03

    def test_atomic_save_leaves_no_temp(self, defaults_file, tmp_path):
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        user_file = user_dir / "settings.json"
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        sm.save()
        leftovers = [f for f in user_dir.iterdir() if f.name != user_file.name]
        assert leftovers == []

    def test_invalid_numbers_clamped(self, defaults_file, user_file):
        user_file.write_text(json.dumps({"avatar": {"scale": 99.0},
                                         "audio": {"silence_ms": "banana"}}),
                             encoding="utf-8")
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("avatar.scale") == 2.0  # clamped to range max
        assert sm.get("audio.silence_ms") == 300  # junk -> default

    def test_corrupt_user_file_falls_back(self, defaults_file, user_file):
        user_file.write_text("{ this is not json", encoding="utf-8")
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("avatar.scale") == 0.55

    def test_missing_defaults_raises(self, tmp_path, user_file):
        with pytest.raises(SettingsError):
            SettingsManager(user_path=user_file, defaults_path=tmp_path / "nope.json")

    def test_reset_to_defaults(self, defaults_file, user_file):
        user_file.write_text(json.dumps({"avatar": {"scale": 0.9}}), encoding="utf-8")
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        sm.reset_to_defaults()
        assert sm.get("avatar.scale") == 0.55

    def test_get_unknown_key_returns_default_arg(self, defaults_file, user_file):
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("no.such.key", "fallback") == "fallback"

    def test_bool_coercion(self, defaults_file, user_file):
        user_file.write_text(json.dumps({"animation": {"breathing": "true"},
                                         "overlay": {"always_on_top": 0}}),
                             encoding="utf-8")
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("animation.breathing") is True
        assert sm.get("overlay.always_on_top") is False

    def test_device_index_int_or_none(self, defaults_file, user_file):
        user_file.write_text(json.dumps({"audio": {"device_index": 3}}), encoding="utf-8")
        sm = SettingsManager(user_path=user_file, defaults_path=defaults_file)
        assert sm.get("audio.device_index") == 3
        sm.set("audio.device_index", None)
        assert sm.get("audio.device_index") is None
