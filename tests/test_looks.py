"""3D LUT parsing, application and built-in looks."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from webcam_mods.mods import looks
from webcam_mods.mods.looks import (
    BUILTIN_LOOKS,
    MAX_CUBE_BYTES,
    MAX_CUBE_SIZE,
    ColorLook,
    builtin_look,
    load_cube,
    parse_cube,
)


def cube_text(
    size: int,
    *,
    header: str = "",
    swap_rb: bool = False,
    scale: float = 1.0,
    rows: int | None = None,
) -> str:
    """Identity (or red/blue swapped) cube, red index varying fastest."""
    lines = [header, f"LUT_3D_SIZE {size}"] if header else [f"LUT_3D_SIZE {size}"]
    top = size - 1
    for b in range(size):
        for g in range(size):
            for r in range(size):
                out = (b, g, r) if swap_rb else (r, g, b)
                lines.append(" ".join(f"{v / top * scale:.6f}" for v in out))
    return "\n".join(lines[: len(lines) if rows is None else rows + 1]) + "\n"


def random_frame(h: int = 32, w: int = 48, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def max_diff(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max())


def channel_spread(frame: np.ndarray) -> int:
    return int(frame.max(axis=2).max()) - int(frame.min(axis=2).min())


class ParseCubeTests(unittest.TestCase):
    def test_identity_cubes_round_trip_within_quantization(self) -> None:
        frame = random_frame()
        for size in (2, 17):
            with self.subTest(size=size):
                table = parse_cube(cube_text(size))
                self.assertEqual(table.shape, (size, size, size, 3))
                self.assertEqual(table.dtype, np.float32)
                out = ColorLook(table)(frame)
                self.assertLessEqual(max_diff(out, frame), 2)

    def test_red_index_varies_fastest(self) -> None:
        table = parse_cube(cube_text(3))
        # table[b, g, r] holds rgb; stepping r moves along the first output channel
        np.testing.assert_allclose(table[0, 0, 2], [1, 0, 0])
        np.testing.assert_allclose(table[0, 2, 0], [0, 1, 0])
        np.testing.assert_allclose(table[2, 0, 0], [0, 0, 1])

    def test_swapped_cube_swaps_red_and_blue(self) -> None:
        frame = random_frame()
        out = ColorLook(parse_cube(cube_text(5, swap_rb=True)))(frame)
        self.assertLessEqual(max_diff(out, frame[:, :, ::-1]), 2)
        self.assertGreater(max_diff(out, frame), 20)

    def test_matches_float_trilinear_reference(self) -> None:
        rng = np.random.default_rng(5)
        n = 5
        table = rng.random((n, n, n, 3), dtype=np.float32)
        frame = random_frame(24, 24, seed=6)
        # sample at the center of each 7-bit bucket, like the dense table
        pos = ((frame >> 1) * 2 + 0.5) / 255 * (n - 1)
        low = np.minimum(pos.astype(int), n - 2)
        frac = pos - low
        expected = np.zeros(frame.shape, np.float64)
        for corner in range(8):
            bits = [(corner >> i) & 1 for i in range(3)]
            weight = np.ones(frame.shape[:2])
            for axis in range(3):
                f = frac[:, :, axis]
                weight = weight * (f if bits[axis] else 1 - f)
            idx = tuple(low[:, :, a] + bits[a] for a in range(3))
            expected += weight[:, :, None] * table[idx]
        expected_bgr = np.rint(expected[:, :, ::-1] * 255)
        out = ColorLook(table)(frame)
        self.assertLessEqual(max_diff(out, expected_bgr.astype(np.uint8)), 1)

    def test_domain_scales_input_range(self) -> None:
        # data spans 0..2 over a 0..2 domain, so 0..1 inputs map through unchanged
        text = "DOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 2 2\n" + cube_text(5, scale=2.0)
        frame = random_frame()
        out = ColorLook(parse_cube(text))(frame)
        self.assertLessEqual(max_diff(out, frame), 3)

    def test_domain_max_below_one_saturates(self) -> None:
        text = "DOMAIN_MIN 0 0 0\nDOMAIN_MAX 0.5 1 1\n" + cube_text(3)
        look = ColorLook(parse_cube(text))
        frame = np.zeros((1, 4, 3), np.uint8)
        frame[0, :, 2] = [0, 32, 64, 200]  # red channel only
        out = look(frame)
        expected_red = [0, 64, 128, 255]  # min(2 * x, 1)
        for got, want in zip(out[0, :, 2], expected_red):
            self.assertLessEqual(abs(int(got) - want), 3)
        self.assertLessEqual(int(out[..., :2].max()), 2)

    def test_lut_3d_input_range_is_a_uniform_domain(self) -> None:
        text = "LUT_3D_INPUT_RANGE 0.0 2.0\n" + cube_text(5, scale=2.0)
        frame = random_frame()
        self.assertLessEqual(max_diff(ColorLook(parse_cube(text))(frame), frame), 3)

    def test_title_comments_and_blank_lines_are_ignored(self) -> None:
        header = '# made by hand\nTITLE "My # look"\n\n  # indented comment\n'
        plain = parse_cube(cube_text(3))
        noisy = parse_cube(cube_text(3, header=header).replace("\n", " # tail\n\n", 4))
        np.testing.assert_array_equal(plain, noisy)

    def test_accepts_largest_size(self) -> None:
        table = parse_cube(cube_text(MAX_CUBE_SIZE))
        self.assertEqual(table.shape, (MAX_CUBE_SIZE,) * 3 + (3,))

    def test_rejects_malformed_cubes(self) -> None:
        good = cube_text(2)
        data = good.split("\n", 1)[1]
        cases = {
            "1d": "LUT_1D_SIZE 4\n0 0 0\n1 1 1\n",
            "missing size": data,
            "no data": "LUT_3D_SIZE 2\n",
            "empty": "",
            "too few rows": cube_text(3, rows=26),
            "too many rows": good + "0 0 0\n",
            "nan": good.replace("1.000000 1.000000 1.000000", "nan 1 1"),
            "inf": good.replace("1.000000 1.000000 1.000000", "1 inf 1"),
            "extra tokens": good.replace("1.000000 1.000000 1.000000", "1 1 1 1"),
            "too few tokens": good.replace("1.000000 1.000000 1.000000", "1 1"),
            "text value": good.replace("1.000000 1.000000 1.000000", "1 x 1"),
            "too big": f"LUT_3D_SIZE {MAX_CUBE_SIZE + 1}\n0 0 0\n",
            "size one": "LUT_3D_SIZE 1\n0 0 0\n",
            "size text": "LUT_3D_SIZE big\n",
            "data before size": data + good,
            "unknown keyword": good.replace("2\n", "2\nLUT_IN_VIDEO_RANGE\n", 1),
            "bad domain": "DOMAIN_MIN 0 0\n" + good,
            "nan domain": "DOMAIN_MAX nan 1 1\n" + good,
            "empty domain": "DOMAIN_MIN 1 1 1\nDOMAIN_MAX 1 1 1\n" + good,
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                parse_cube(text)


class LoadCubeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_loads_identity_file(self) -> None:
        path = self.dir / "id.cube"
        path.write_text(cube_text(9), encoding="utf-8")
        frame = random_frame()
        self.assertLessEqual(max_diff(load_cube(path)(frame), frame), 2)
        self.assertLessEqual(max_diff(load_cube(str(path))(frame), frame), 2)

    def test_accepts_utf8_bom(self) -> None:
        path = self.dir / "bom.cube"
        path.write_bytes(b"\xef\xbb\xbf" + cube_text(2).encode())
        self.assertIsInstance(load_cube(path), ColorLook)

    def test_rejects_oversized_file(self) -> None:
        path = self.dir / "big.cube"
        path.write_bytes(b"#" * (MAX_CUBE_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            load_cube(path)

    def test_rejects_non_utf8_and_bad_content(self) -> None:
        path = self.dir / "bad.cube"
        path.write_bytes(b"\xff\xfe\x00LUT_3D_SIZE 2\n")
        with self.assertRaisesRegex(ValueError, "utf-8"):
            load_cube(path)
        path.write_text("LUT_1D_SIZE 2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_cube(path)


class ColorLookTests(unittest.TestCase):
    swap = ColorLook(parse_cube(cube_text(5, swap_rb=True)))

    def test_strength_zero_returns_input_pixels(self) -> None:
        frame = random_frame()
        np.testing.assert_array_equal(self.swap(frame, 0.0), frame)
        np.testing.assert_array_equal(self.swap(frame, -1.0), frame)
        np.testing.assert_array_equal(self.swap(frame, float("nan")), frame)

    def test_partial_strength_lies_between_input_and_full_look(self) -> None:
        frame = random_frame()
        full = self.swap(frame, 1.0)
        half = self.swap(frame, 0.5)
        low, high = np.minimum(frame, full), np.maximum(frame, full)
        self.assertTrue(((half >= low) & (half <= high)).all())
        expected = (frame.astype(np.float32) + full) / 2
        self.assertLessEqual(float(np.abs(half - expected).max()), 1.0)
        self.assertLess(
            np.abs(half.astype(int) - frame).mean(),
            np.abs(full.astype(int) - frame).mean(),
        )

    def test_strength_above_one_is_full_look(self) -> None:
        frame = random_frame()
        np.testing.assert_array_equal(self.swap(frame, 3.0), self.swap(frame, 1.0))

    def test_inputs_are_not_mutated_and_shape_dtype_are_kept(self) -> None:
        base = random_frame(40, 56)
        variants = {
            "contiguous": base,
            "strided": base[:, ::2],
            "cropped": base[5:30, 7:50],
            "tiny": base[:1, :1],
        }
        for name, frame in variants.items():
            before = frame.copy()
            for strength in (0.0, 0.4, 1.0):
                with self.subTest(name=name, strength=strength):
                    out = self.swap(frame, strength)
                    self.assertEqual(out.shape, frame.shape)
                    self.assertEqual(out.dtype, np.uint8)
                    np.testing.assert_array_equal(frame, before)
                    if strength > 0:
                        self.assertIsNot(out, frame)

    def test_extremes_stay_in_range(self) -> None:
        frame = np.array([[[0, 0, 0], [255, 255, 255], [0, 255, 0]]], np.uint8)
        out = ColorLook(parse_cube(cube_text(2)))(frame)
        self.assertLessEqual(max_diff(out, frame), 1)

    def test_out_of_range_table_values_are_clipped(self) -> None:
        table = parse_cube(cube_text(2, scale=3.0))
        out = ColorLook(table)(np.full((2, 2, 3), 200, np.uint8))
        self.assertEqual(int(out.min()), 255)

    def test_rejects_malformed_frames_and_tables(self) -> None:
        with self.assertRaises(ValueError):
            self.swap(np.zeros((4, 4), np.uint8))
        with self.assertRaises(ValueError):
            self.swap(np.zeros((4, 4, 3), np.float32))
        with self.assertRaises(ValueError):
            ColorLook(np.zeros((3, 3, 3), np.float32))
        with self.assertRaises(ValueError):
            ColorLook(np.zeros((2, 3, 3, 3), np.float32))
        with self.assertRaises(ValueError):
            ColorLook(np.zeros((1, 1, 1, 3), np.float32))
        with self.assertRaises(ValueError):
            ColorLook(np.full((2, 2, 2, 3), np.nan, np.float32))


class BuiltinLookTests(unittest.TestCase):
    def test_every_builtin_look_changes_the_frame(self) -> None:
        frame = random_frame(48, 64, seed=2)
        before = frame.copy()
        for name in BUILTIN_LOOKS:
            with self.subTest(name=name):
                out = builtin_look(name)(frame)
                self.assertEqual(out.shape, frame.shape)
                self.assertEqual(out.dtype, np.uint8)
                self.assertGreater(float(np.abs(out.astype(int) - frame).mean()), 1.0)
                np.testing.assert_array_equal(frame, before)

    def test_mono_is_gray(self) -> None:
        out = builtin_look("mono")(random_frame(48, 64, seed=3))
        spread = out.max(axis=2).astype(int) - out.min(axis=2).astype(int)
        self.assertLessEqual(int(spread.max()), 1)

    def test_look_characters(self) -> None:
        mid = np.full((1, 1, 3), 128, np.uint8)
        warm, cool = builtin_look("warm")(mid)[0, 0], builtin_look("cool")(mid)[0, 0]
        self.assertGreater(int(warm[2]), int(warm[0]))  # red above blue
        self.assertGreater(int(cool[0]), int(cool[2]))  # blue above red
        black = np.zeros((1, 1, 3), np.uint8)
        white = np.full((1, 1, 3), 255, np.uint8)
        fade = builtin_look("fade")
        self.assertGreater(int(fade(black).min()), 10)
        self.assertLess(int(fade(white).max()), 250)
        vivid = builtin_look("vivid")
        tint = np.array([[[90, 120, 180]]], np.uint8)
        self.assertGreater(channel_spread(vivid(tint)), channel_spread(tint))

    def test_builtin_looks_are_cached(self) -> None:
        for name in BUILTIN_LOOKS:
            with self.subTest(name=name):
                self.assertIs(builtin_look(name), builtin_look(name))
        self.assertIsNot(builtin_look("warm"), builtin_look("cool"))

    def test_unknown_name_raises(self) -> None:
        for name in ("", "sepia", "WARM"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unknown"):
                builtin_look(name)

    def test_module_exposes_documented_limits(self) -> None:
        self.assertEqual(looks.MAX_CUBE_BYTES, 16 * 1024 * 1024)
        self.assertEqual(looks.MAX_CUBE_SIZE, 65)


if __name__ == "__main__":
    unittest.main()
