"""Exposure, focus and anti-flicker set on the camera hardware."""

from dataclasses import asdict
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from webcam_mods.camera_controls import CameraControls, _native, _percent
from webcam_mods.control import Controller, run_profile
from webcam_mods.profiles import RESTART_FIELDS, Profile, ProfileStore

_FORMATS = {"fcam": "=I", "fcnv": "=f", "fcnr": "=2d"}


class FakeCamera:
    """CoreMediaIO stand-in: control objects with auto, value and range."""

    def __init__(self) -> None:
        self.state = {
            10: {"fcam": 1, "fcnv": 250.0, "fcnr": (3.0, 2047.0)},  # exposure
            11: {"fcam": 0, "fcnv": 40.0, "fcnr": (0.0, 250.0)},  # focus
            12: {"fcam": 0, "fcnv": 2.0, "fcnr": (0.0, 0.0)},  # power line
            13: {"fcam": 0, "fcnv": 1.0},  # white balance, no range
        }
        self.found = {"xpsr": 10, "fcus": 11, "pwfq": 12, "temp": 13}
        self.refused: set[tuple[int, str]] = set()
        self.lookups = 0

    def controls(self, device_uid: str) -> dict[str, int]:
        self.lookups += 1
        return dict(self.found) if device_uid == "c920" else {}

    def read(self, target: int, selector: str) -> bytes | None:
        value = self.state[target].get(selector)
        if value is None:
            return None
        values = value if isinstance(value, tuple) else (value,)
        return struct.pack(_FORMATS[selector], *values)

    def write(self, target: int, selector: str, data: bytes) -> bool:
        if (target, selector) in self.refused:
            return False
        self.state[target][selector] = struct.unpack(_FORMATS[selector], data)[0]
        return True


class HardwareProfileTests(unittest.TestCase):
    def test_fields_are_validated_and_apply_live(self) -> None:
        profile = Profile.parse(
            {"camera_exposure": 0, "camera_focus": 100, "anti_flicker": "50hz"}
        )
        self.assertEqual(
            (profile.camera_exposure, profile.camera_focus, profile.anti_flicker),
            (0, 100, "50hz"),
        )
        for config in (
            {"camera_exposure": 101},
            {"camera_exposure": 50.0},
            {"camera_focus": True},
            {"camera_focus": -1},
            {"anti_flicker": "auto"},
            {"anti_flicker": 50},
        ):
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, next(iter(config))):
                    Profile.parse(config)
        self.assertFalse(
            {"camera_exposure", "camera_focus", "anti_flicker"} & RESTART_FIELDS
        )

    def test_exposure_percent_follows_stops_and_focus_is_linear(self) -> None:
        self.assertEqual(_native("exposure", 0, 3, 2047), 3)
        self.assertEqual(_native("exposure", 100, 3, 2047), 2047)
        # each tenth of the slider is the same exposure ratio
        self.assertAlmostEqual(_native("exposure", 72, 3, 2047), 245, delta=3)
        self.assertEqual(_percent("exposure", 250, 3, 2047), 72)
        self.assertEqual(_native("focus", 16, 0, 250), 40)
        self.assertEqual(_percent("focus", 40, 0, 250), 16)
        self.assertEqual(_percent("focus", 900, 0, 250), 100)


class CameraControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.camera = FakeCamera()
        self.warnings: list[str] = []

    def controls(self, profile: Profile, uid: str | None = "c920") -> CameraControls:
        return CameraControls(
            uid, profile, on_warning=self.warnings.append, backend=self.camera
        )

    def test_describe_lists_adjustable_controls_as_profile_values(self) -> None:
        self.assertEqual(
            self.controls(Profile()).describe(),
            {
                "exposure": {"auto": True, "value": 72},
                "focus": {"auto": False, "value": 16},
                "anti_flicker": "60hz",
            },
        )
        del self.camera.state[10]["fcnr"]
        self.camera.state[12]["fcnv"] = 3.0
        self.assertEqual(
            self.controls(Profile()).describe(),
            {"focus": {"auto": False, "value": 16}, "anti_flicker": "auto"},
        )
        self.assertEqual(self.controls(Profile(), "built-in").describe(), {})

    def test_settings_wait_for_streaming_and_are_put_back(self) -> None:
        state = self.camera.state
        controls = self.controls(Profile(camera_exposure=0, anti_flicker="50hz"))
        controls.update(Profile(camera_exposure=100, anti_flicker="50hz"))
        self.assertEqual(state[10], {"fcam": 1, "fcnv": 250.0, "fcnr": (3, 2047)})
        controls.start()
        # the newest profile applies once frames arrive
        self.assertEqual((state[10]["fcam"], state[10]["fcnv"]), (0, 2047))
        self.assertEqual(state[12]["fcnv"], 1)
        controls.update(
            Profile(camera_exposure=100, camera_focus=100, anti_flicker="off")
        )
        self.assertEqual((state[11]["fcam"], state[11]["fcnv"]), (0, 250))
        self.assertEqual(state[12]["fcnv"], 0)
        # clearing a setting hands that control back right away
        controls.update(Profile(camera_focus=100, anti_flicker="off"))
        self.assertEqual(state[10]["fcam"], 1)
        controls.close()
        self.assertEqual((state[11]["fcam"], state[11]["fcnv"]), (0, 40))
        self.assertEqual(state[12]["fcnv"], 2)
        controls.update(Profile(camera_exposure=50))
        self.assertEqual(state[10]["fcam"], 1)
        self.assertEqual(self.warnings, [])

    def test_profiles_without_hardware_settings_never_look(self) -> None:
        controls = self.controls(Profile(exposure=1.0))
        controls.start()
        controls.update(Profile(brightness=20))
        controls.close()
        self.assertEqual(self.camera.lookups, 0)

    def test_unsupported_and_refused_settings_warn(self) -> None:
        del self.camera.found["fcus"]
        self.camera.refused.add((12, "fcnv"))
        controls = self.controls(Profile(camera_focus=10, anti_flicker="50hz"))
        controls.start()
        self.assertEqual(
            self.warnings,
            [
                "This camera has no adjustable focus",
                "The camera did not accept the anti-flicker setting",
            ],
        )
        self.warnings.clear()
        no_camera = self.controls(Profile(camera_exposure=5), uid=None)
        no_camera.start()
        self.assertEqual(
            self.warnings,
            [
                "Camera exposure not set: choose a camera to set its exposure, focus"
                " or flicker"
            ],
        )
        self.warnings.clear()
        with patch("webcam_mods.camera_controls.sys") as system:
            system.platform = "linux"
            linux = CameraControls(
                "c920", Profile(anti_flicker="60hz"), on_warning=self.warnings.append
            )
            linux.start()
        self.assertEqual(
            self.warnings,
            [
                "Camera anti-flicker not set: camera exposure, focus and flicker need"
                " macOS"
            ],
        )


class SessionHardwareTests(unittest.TestCase):
    def test_run_profile_sets_the_camera_while_frames_flow(self) -> None:
        camera = FakeCamera()
        seen: list[tuple[int, float]] = []

        def loop(**options: object) -> None:
            seen.append((camera.state[10]["fcam"], camera.state[10]["fcnv"]))
            options["on_ready"]()  # type: ignore[operator]
            seen.append((camera.state[10]["fcam"], camera.state[10]["fcnv"]))

        ready = Mock()
        with (
            patch("webcam_mods.camera_controls.sys") as system,
            patch("webcam_mods.macos.cmio.CoreMediaIO", return_value=camera),
            patch("webcam_mods.capture.camera_index_for_id", return_value=0),
            patch("webcam_mods.capture.create_camera"),
            patch("webcam_mods.loopback.live_loop", side_effect=loop),
        ):
            system.platform = "darwin"
            run_profile(
                Profile(camera_id="c920", camera_exposure=100),
                threading.Event(),
                ready,
                lambda _: None,
            )
        self.assertEqual(seen, [(1, 250), (0, 2047)])
        ready.assert_called_once_with()
        # the run is over, so the camera is back on automatic exposure
        self.assertEqual(camera.state[10]["fcam"], 1)

    def test_shared_screens_leave_camera_hardware_alone(self) -> None:
        with (
            patch("webcam_mods.camera_controls.CameraControls") as controls,
            patch("webcam_mods.loopback.live_loop"),
            patch("webcam_mods.input.screen.Screen"),
        ):
            run_profile(
                Profile(
                    source="screen", screen_region=(0, 0, 640, 480), camera_focus=5
                ),
                threading.Event(),
                lambda: None,
                lambda _: None,
            )
        controls.assert_not_called()


class ControllerHardwareTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.controls = Mock()
        self.started = threading.Event()

        def runner(profile, stop, ready, source_ready, **callbacks):
            callbacks["on_effect"](Mock())
            callbacks["on_controls"](self.controls)
            ready()
            self.started.set()
            stop.wait(5)

        with patch("webcam_mods.control.run_profile", runner):
            self.controller = Controller(
                ProfileStore(Path(directory.name) / "profiles.db"), lambda _: None
            )
        self.addCleanup(self.controller.stop)

    def test_live_updates_reach_the_camera(self) -> None:
        self.controller.start(Profile(camera_id="c920"), "preview")
        self.assertTrue(self.started.wait(1))
        profile = Profile(camera_id="c920", camera_exposure=30)
        self.controller.dispatch("session.update", {"config": asdict(profile)})
        self.controls.update.assert_called_once_with(profile)
        self.controller.stop()
        self.assertIsNone(self.controller.controls)

    def test_cameras_controls_describes_one_camera(self) -> None:
        dispatch = self.controller.dispatch
        for params in ({}, {"id": 5}, {"id": "c920", "extra": 1}):
            with self.subTest(params=params):
                with self.assertRaisesRegex(ValueError, "camera id"):
                    dispatch("cameras.controls", params)
        with (
            patch("webcam_mods.control.sys") as system,
            patch("webcam_mods.camera_controls.CameraControls") as controls,
        ):
            system.platform = "darwin"
            controls.return_value.describe.return_value = {"anti_flicker": "60hz"}
            self.assertEqual(
                dispatch("cameras.controls", {"id": "c920"}),
                {"anti_flicker": "60hz"},
            )
            system.platform = "linux"
            with self.assertRaisesRegex(RuntimeError, "macOS"):
                dispatch("cameras.controls", {"id": "c920"})
        self.assertEqual(controls.call_args.args[0], "c920")


if __name__ == "__main__":
    unittest.main()
