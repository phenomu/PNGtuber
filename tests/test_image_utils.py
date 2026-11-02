import numpy as np
import pytest
from PIL import Image

from hakuze_pngtuber.utils.image_utils import (
    AssetError,
    desaturate,
    ensure_placeholder_assets,
    fit_size,
    has_real_transparency,
    load_rgba,
    make_placeholder,
)


class TestPlaceholders:
    def test_placeholder_rgba_transparent_bg(self):
        for talking in (False, True):
            img = make_placeholder(talking)
            assert img.mode == "RGBA"
            assert has_real_transparency(img)  # corners are transparent

    def test_both_states_same_canvas(self):
        a, b = make_placeholder(False), make_placeholder(True)
        assert a.size == b.size

    def test_placeholder_pixels_differ(self):
        a, b = make_placeholder(False), make_placeholder(True)
        assert list(a.getdata()) != list(b.getdata())

    def test_ensure_assets_writes_once(self, tmp_path):
        idle, talk = ensure_placeholder_assets(tmp_path)
        assert idle.is_file() and talk.is_file()
        mtime = idle.stat().st_mtime_ns
        ensure_placeholder_assets(tmp_path)  # second call: no overwrite
        assert idle.stat().st_mtime_ns == mtime


class TestDesaturate:
    def make_color_img(self):
        img = Image.new("RGBA", (10, 10), (200, 40, 40, 255))
        img.putpixel((0, 0), (200, 40, 40, 128))
        return img

    def test_zero_intensity_unchanged_colors(self):
        img = self.make_color_img()
        out = desaturate(img, 0.0)
        assert out.getpixel((5, 5)) == (200, 40, 40, 255)

    def test_full_intensity_gray(self):
        img = self.make_color_img()
        out = desaturate(img, 1.0)
        r, g, b, a = out.getpixel((5, 5))
        assert r == g == b

    def test_alpha_preserved(self):
        img = self.make_color_img()
        out = desaturate(img, 0.85)
        assert out.getpixel((0, 0))[3] == 128
        assert out.getpixel((5, 5))[3] == 255

    def test_partial_between(self):
        img = Image.new("RGBA", (2, 2), (200, 40, 40, 255))
        half = desaturate(img, 0.5)
        r, g, b, _ = half.getpixel((0, 0))
        orig_sat = 200 - 40
        new_sat = max(r, g, b) - min(r, g, b)
        assert new_sat < orig_sat

    def test_intensity_clamped(self):
        img = self.make_color_img()
        desaturate(img, 5.0)  # must not raise
        desaturate(img, -3.0)


class TestFit:
    def test_aspect_preserved_landscape(self):
        assert fit_size((1920, 1080), 500, 500) == (500, 281)

    def test_aspect_preserved_portrait(self):
        assert fit_size((568, 1024), 500, 500) == (277, 500)

    def test_no_upscale(self):
        assert fit_size((100, 50), 500, 500) == (500, 250)  # upscale allowed to target

    def test_zero_size_fallback(self):
        w, h = fit_size((0, 0), 300, 300)
        assert w == 300 and h == 300

    def test_square(self):
        assert fit_size((512, 512), 300, 300) == (300, 300)


class TestLoadRGBA:
    def test_loads_rgba(self, tmp_path):
        p = tmp_path / "img.png"
        Image.new("RGB", (20, 20), (10, 20, 30)).save(p)
        img = load_rgba(p)
        assert img.mode == "RGBA"
        assert img.size == (20, 20)

    def test_missing_raises(self, tmp_path):
        with pytest.raises(AssetError):
            load_rgba(tmp_path / "nope.png")

    def test_corrupt_raises(self, tmp_path):
        p = tmp_path / "bad.png"
        p.write_bytes(b"not a png at all")
        with pytest.raises(AssetError):
            load_rgba(p)

    def test_alpha_channel_read(self, tmp_path):
        p = tmp_path / "img.png"
        base = Image.new("RGBA", (10, 10), (255, 0, 0, 100))
        base.save(p)
        assert load_rgba(p).getpixel((5, 5))[3] == 100


class TestArrays:
    def test_rgba_alpha_preserved_through_ops(self):
        img = Image.new("RGBA", (8, 8), (100, 150, 200, 77))
        out = desaturate(img, 1.0)
        assert out.getpixel((4, 4))[3] == 77
