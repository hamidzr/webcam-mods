"""Profile looks: built-in filters, .cube files and strength, applied live."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from webcam_mods.effects import ProfileEffect
from webcam_mods.mods.looks import BUILTIN_LOOKS
from webcam_mods.profiles import LOOKS, RESTART_FIELDS, Profile, ProfileStore
from webcam_mods.settings import StartupSettings


def swapped_cube() -> str:
    """2-point cube that swaps red and blue; red varies fastest in file order."""
    rows = [
        f"{b} {g} {r}" for b in (0, 1) for g in (0, 1) for r in (0, 1)
    ]  # output rgb = input bgr
    return "LUT_3D_SIZE 2\n" + "\n".join(rows) + "\n"


class LookProfileTests(unittest.TestCase):
    def test_choices_match_builtins_and_custom_needs_a_path(self) -> None:
        self.assertEqual(set(LOOKS) - {"none", "custom"}, set(BUILTIN_LOOKS))
        self.assertEqual(Profile.parse({"look": "film"}).look_strength, 100)
        with self.assertRaisesRegex(ValueError, "invalid look"):
            Profile.parse({"look": "sepia"})
        with self.assertRaisesRegex(ValueError, "custom look requires look_path"):
            Profile.parse({"look": "custom"})
        with self.assertRaisesRegex(ValueError, "look_strength"):
            Profile.parse({"look_strength": 101})
        self.assertFalse({"look", "look_path", "look_strength"} & RESTART_FIELDS)

    def test_store_saves_absolute_look_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save("Graded", {"look": "custom", "look_path": "~/grade.cube"})
            self.assertEqual(
                store.get("Graded").look_path, str(Path.home() / "grade.cube")
            )


class ProfileEffectLookTests(unittest.TestCase):
    frame = np.full((48, 64, 3), (10, 20, 200), np.uint8)

    def effect(self, profile: Profile) -> ProfileEffect:
        effect = ProfileEffect(profile, StartupSettings(out_width=64, out_height=48))
        self.addCleanup(effect.close)
        return effect

    def test_builtin_look_and_strength_apply_live(self) -> None:
        effect = self.effect(Profile(look="mono"))
        mono = effect(self.frame)
        assert mono is not None
        self.assertEqual(int(np.ptp(mono[0, 0].astype(int))), 0)
        effect.update(Profile(look="mono", look_strength=50))
        half = effect(self.frame)
        assert half is not None
        self.assertGreater(int(half[0, 0, 2]), int(mono[0, 0, 2]))
        self.assertLess(int(half[0, 0, 2]), 200)
        effect.update(Profile(look="mono", look_strength=0))
        np.testing.assert_array_equal(effect(self.frame), self.frame)

    def test_custom_cube_applies_and_bad_files_fail_on_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cube = Path(directory) / "swap.cube"
            cube.write_text(swapped_cube())
            effect = self.effect(Profile(look="custom", look_path=str(cube)))
            result = effect(self.frame)
            assert result is not None
            np.testing.assert_allclose(result[0, 0], (200, 20, 10), atol=2)
            with self.assertRaisesRegex(ValueError, "look file could not be read"):
                effect.update(
                    Profile(look="custom", look_path=str(cube.with_name("gone.cube")))
                )
            bad = Path(directory) / "bad.cube"
            bad.write_text("LUT_3D_SIZE 2\n0 0 0\n")
            with self.assertRaisesRegex(ValueError, "data rows"):
                effect.update(Profile(look="custom", look_path=str(bad)))
            # the running look stays after a rejected update
            result = effect(self.frame)
            assert result is not None
            np.testing.assert_allclose(result[0, 0], (200, 20, 10), atol=2)


if __name__ == "__main__":
    unittest.main()
