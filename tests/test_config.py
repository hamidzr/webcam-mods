import json
from pathlib import Path
import tempfile
import unittest

from webcam_mods.utils.config import Config


def good(**overrides):
    conf = {"crop_dims": [10, 8], "crop_pos": [2, 1], "pad_size": [0, 2]}
    conf.update(overrides)
    return conf


class ConfigValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(path=None, width=20, height=10)

    def test_accepts_in_bounds_values(self) -> None:
        self.assertTrue(self.config.valid(good()))

    def test_rejects_out_of_bounds_or_malformed(self) -> None:
        bad = [
            good(crop_dims=[0, 8]),
            good(crop_dims=[21, 8]),
            good(crop_pos=[11, 1]),  # pos + dims exceeds width
            good(crop_pos=[-1, 0]),
            good(pad_size=[1, 0]),  # odd padding
            good(pad_size=[10, 0]),  # padding not below dims
            good(crop_dims=[10]),
            good(crop_dims=[10.0, 8]),
            good(crop_dims=[True, 8]),  # bool is not an int here
            good(crop_dims="10x8"),
        ]
        for conf in bad:
            with self.subTest(conf=conf):
                self.assertFalse(self.config.valid(conf))
        self.assertFalse(self.config.valid({"crop_dims": [10, 8]}))


class ConfigPersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "c.json"
            config = Config(path, width=20, height=10)
            config.crop_dims, config.crop_pos, config.pad_size = [10, 8], [2, 1], [0, 2]
            config.persist()
            loaded = Config(path, width=20, height=10)
            self.assertEqual(loaded.to_dict(), good())
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["c.json"])

    def test_invalid_or_corrupt_files_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "c.json"
            for text in ("not json", "[1, 2]", json.dumps(good(crop_dims=[99, 8]))):
                with self.subTest(text=text):
                    path.write_text(text)
                    config = Config(path, width=20, height=10)
                    self.assertEqual(config.crop_dims, [20, 10])
                    self.assertEqual(config.crop_pos, [0, 0])
                    self.assertIsNone(config.load())

    def test_saved_config_for_larger_frame_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "c.json"
            path.write_text(json.dumps(good(crop_dims=[10, 8], crop_pos=[2, 1])))
            config = Config(path, width=10, height=8)
            self.assertEqual(config.crop_pos, [0, 0])

    def test_failed_persist_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Config(Path(directory) / "c.json", width=20, height=10)
            config.crop_dims = [object(), 1]  # type: ignore[list-item]
            with self.assertRaises(TypeError):
                config.persist()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_reset_restores_full_frame(self) -> None:
        config = Config(path=None, width=20, height=10)
        config.crop_dims, config.crop_pos, config.pad_size = [4, 4], [1, 1], [2, 2]
        config.reset()
        self.assertEqual(
            config.to_dict(),
            {"crop_dims": [20, 10], "crop_pos": [0, 0], "pad_size": [0, 0]},
        )


if __name__ == "__main__":
    unittest.main()
