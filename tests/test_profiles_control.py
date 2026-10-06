from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.control import Controller
from webcam_mods.profiles import Profile, ProfileStore


class ProfileTests(unittest.TestCase):
    def test_validates_without_coercion(self):
        for config in (
            {"track": 1},
            {"width": True},
            {"fps": float("nan")},
            {"blur_kernel": 2},
            {"effect": "image"},
            {"unexpected": 1},
            {"capture": []},
        ):
            with (
                self.subTest(config=config),
                self.assertRaises((ValueError, TypeError)),
            ):
                Profile.parse(config)

    def test_sqlite_roundtrip_and_literal_name(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            name = "'; DROP TABLE profiles; --"
            store.save(name, {"effect": "blur", "track": True})
            self.assertEqual(store.get(name), Profile(effect="blur", track=True))
            self.assertEqual(store.list()[0]["config"]["effect"], "blur")
            store.save(name, {"brightness": 20})
            self.assertEqual(store.get(name).brightness, 20)
            store.delete(name)
            self.assertEqual(store.list(), [])

    def test_saved_image_path_is_independent_of_caller_directory(self):
        from contextlib import chdir

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProfileStore(root / "p.db")
            image = root / "background.png"
            image.write_bytes(b"fixture")
            with chdir(root):
                store.save("image", {"effect": "image", "image_path": "background.png"})
            with chdir(root.parent):
                saved_path = Path(store.get("image").image_path)
                self.assertTrue(saved_path.is_absolute())
                self.assertEqual(saved_path.read_bytes(), b"fixture")
            store.save("home", {"effect": "image", "image_path": "~/background.png"})
            self.assertEqual(
                store.get("home").image_path, str(Path.home() / "background.png")
            )

    def test_future_schema_is_rejected(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.db"
            db = sqlite3.connect(path)
            db.execute("PRAGMA user_version=2")
            db.close()
            with self.assertRaisesRegex(RuntimeError, "schema"):
                ProfileStore(path)


class ControlTests(unittest.TestCase):
    def test_stop_releases_worker_before_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            started = threading.Event()
            released = []
            source = Mock()

            def runner(profile, stop, ready, source_ready):
                source_ready(source)
                ready()
                started.set()
                stop.wait(2)
                released.append(True)

            controller = Controller(
                ProfileStore(Path(directory) / "p.db"), events.append, runner
            )
            controller.start(Profile())
            self.assertTrue(started.wait(1))
            self.assertEqual(controller.status()["state"], "running")
            with self.assertRaisesRegex(RuntimeError, "active"):
                controller.start(Profile())
            controller.stop()
            self.assertEqual(released, [True])
            source.request_stop.assert_called_once()
            self.assertEqual(controller.status()["state"], "idle")
            controller.start(Profile())
            controller.stop()
            self.assertEqual(len(released), 2)

    def test_failed_start_does_not_report_running(self):
        def runner(*args):
            raise RuntimeError("camera denied")

        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(
                ProfileStore(Path(directory) / "p.db"), lambda event: None, runner
            )
            controller.start(Profile())
            controller.thread.join(1)
            self.assertEqual(
                controller.status(), {"state": "error", "error": "camera denied"}
            )

    def test_tracking_owns_cleanup_and_stable_background_size(self):
        from webcam_mods.effects import TrackingEffect
        from webcam_mods.settings import StartupSettings
        from webcam_mods.geometry import Rect

        detector, tracker, background = Mock(), Mock(), Mock()
        tracker.generate_crop.return_value = Rect(l=0, t=0, w=32, h=32)
        background.side_effect = lambda frame: frame
        with (
            patch("webcam_mods.mods.mp_face.FaceDetector", return_value=detector),
            patch("webcam_mods.mods.camera_motion.CropTracker", return_value=tracker),
        ):
            effect = TrackingEffect(StartupSettings(), background)
            result = effect(np.zeros((100, 100, 3), dtype=np.uint8))
            self.assertEqual(result.shape, (480, 640, 3))
            effect.close()
            effect.close()
        detector.close.assert_called_once()
        tracker.close.assert_called_once()
        background.close.assert_called_once()

    def test_tracking_cleanup_transfers_to_timed_out_worker(self):
        from webcam_mods.entry import Common, _run
        from webcam_mods.frame_producer import WorkerShutdownTimeout
        from webcam_mods.settings import StartupSettings

        effect = Mock()
        cleanups = []

        def loop(**kwargs):
            cleanups.append(kwargs["processing_cleanup"])
            raise WorkerShutdownTimeout("busy")

        with (
            patch("webcam_mods.entry.live_loop", side_effect=loop),
            patch("webcam_mods.entry.RunSession"),
        ):
            with self.assertRaises(WorkerShutdownTimeout):
                _run(
                    Common(controls=False, settings=StartupSettings()),
                    effect,
                    source=Mock(),
                    prepare=False,
                )
        effect.close.assert_not_called()
        cleanups[0]()
        effect.close.assert_called_once()


class ControlRegressionTests(unittest.TestCase):
    def test_run_profile_cleanup_ownership(self):
        from webcam_mods.control import run_profile
        from webcam_mods.frame_producer import WorkerShutdownTimeout

        for error, expected in (
            (RuntimeError("startup"), 1),
            (KeyboardInterrupt(), 1),
            (WorkerShutdownTimeout("busy"), 0),
        ):
            with self.subTest(error=error):
                effect = Mock()
                with (
                    patch("webcam_mods.effects.ProfileEffect", return_value=effect),
                    patch("webcam_mods.capture.create_camera", return_value=Mock()),
                    patch("webcam_mods.loopback.live_loop", side_effect=error),
                ):
                    with self.assertRaises(type(error)):
                        run_profile(
                            Profile(),
                            threading.Event(),
                            lambda: None,
                            lambda source: None,
                        )
                self.assertEqual(effect.close.call_count, expected)
        effect = Mock()
        with (
            patch("webcam_mods.effects.ProfileEffect", return_value=effect),
            patch(
                "webcam_mods.capture.create_camera", side_effect=ValueError("camera")
            ),
        ):
            with self.assertRaises(ValueError):
                run_profile(
                    Profile(), threading.Event(), lambda: None, lambda source: None
                )
        effect.close.assert_called_once()

    def test_stop_before_source_ready_cancels_source_and_never_reports_running(self):
        with tempfile.TemporaryDirectory() as directory:
            reached = threading.Event()
            events = []
            source = Mock()

            def runner(profile, stop, ready, source_ready):
                reached.set()
                stop.wait(1)
                source_ready(source)
                ready()

            controller = Controller(
                ProfileStore(Path(directory) / "p.db"), events.append, runner
            )
            controller.start(Profile())
            self.assertTrue(reached.wait(1))
            controller.stop()
            source.request_stop.assert_called_once()
            states = [event["data"]["state"] for event in events]
            self.assertEqual(states, ["starting", "stopping", "idle"])

    def test_camera_auto_keeps_public_index_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = Controller(
                ProfileStore(Path(directory) / "p.db"), lambda _: None
            )
            camera = Mock(input_index=3, excluded_reason=None)
            camera.name = "Input"
            with (
                patch("webcam_mods.control.sys.platform", "darwin"),
                patch(
                    "webcam_mods.macos.capture.camera_inventory", return_value=[camera]
                ) as inventory,
            ):
                self.assertEqual(
                    controller.dispatch("cameras.list", {"capture": "auto"}),
                    [{"index": 3, "name": "Input"}],
                )
                inventory.assert_called_once_with("auto")

    def test_protocol_subprocess_survives_malformed_input_and_eof(self):
        import os
        import json
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            requests = [
                {"id": 1, "method": "hello"},
                {
                    "id": 2,
                    "method": "profiles.save",
                    "params": {"name": "fixture", "config": {"track": True}},
                },
                {"id": 3, "method": "profiles.list"},
                {"id": 4, "method": "unknown"},
            ]
            for shutdown in (False, True):
                messages = requests + (
                    [{"id": 5, "method": "shutdown"}] if shutdown else []
                )
                result = subprocess.run(
                    [sys.executable, "-m", "webcam_mods.control"],
                    input="malformed\n"
                    + "\n".join(json.dumps(message) for message in messages)
                    + "\n",
                    text=True,
                    capture_output=True,
                    env={**os.environ, "XDG_CONFIG_HOME": directory},
                    timeout=10,
                    check=True,
                )
                replies = [json.loads(line) for line in result.stdout.splitlines()]
                self.assertEqual(len(replies), len(messages) + 1)
                self.assertIn("error", replies[0])
                self.assertEqual(replies[1]["result"]["protocol"], 1)
                self.assertTrue(replies[3]["result"][0]["config"]["track"])
                self.assertEqual(replies[4]["error"], "unknown method")
                if shutdown:
                    self.assertEqual(replies[-1]["result"], {"state": "idle"})

    def test_profile_run_rejects_explicit_shared_flags_in_both_positions(self):
        from typer.testing import CliRunner
        from webcam_mods.entry import app

        for args in (
            ["--input-width", "800", "profile-run", "fixture"],
            ["profile-run", "fixture", "--input-width", "800"],
        ):
            result = CliRunner().invoke(app, args)
            self.assertEqual(result.exit_code, 2, result.output)
            self.assertIn("uses saved settings", result.output)

    def test_broken_protocol_output_requests_cancellation_and_cleanup(self):
        import io
        from webcam_mods.control import main

        source = Mock()
        controller = Mock(stop_event=threading.Event(), source=source)
        controller.dispatch.return_value = {"state": "running"}
        output = Mock()
        output.write.side_effect = BrokenPipeError("closed")
        with (
            patch("webcam_mods.control.ProfileStore"),
            patch("webcam_mods.control.Controller", return_value=controller),
            patch(
                "webcam_mods.control.sys.stdin",
                io.StringIO('{"id":1,"method":"status"}\n'),
            ),
            patch("webcam_mods.control.sys.stdout", output),
        ):
            main()
        self.assertTrue(controller.stop_event.is_set())
        source.request_stop.assert_called_once()
        controller.stop.assert_called_once()


class ProfileEffectTests(unittest.TestCase):
    def test_tracking_background_brightness_order(self):
        from webcam_mods.effects import ProfileEffect
        from webcam_mods.geometry import Rect
        from webcam_mods.settings import StartupSettings

        detector, tracker, background = Mock(), Mock(), Mock()
        tracker.generate_crop.return_value = Rect(l=0, t=0, w=20, h=20)
        seen = []

        def apply_background(frame):
            seen.append(frame.copy())
            return np.full(frame.shape, 40, dtype=np.uint8)

        background.side_effect = apply_background
        with (
            patch("webcam_mods.mods.mp_face.FaceDetector", return_value=detector),
            patch("webcam_mods.mods.camera_motion.CropTracker", return_value=tracker),
            patch("webcam_mods.entry.BackgroundEffect", return_value=background),
        ):
            effect = ProfileEffect(
                Profile(effect="blur", track=True, brightness=20), StartupSettings()
            )
            result = effect(np.full((100, 100, 3), 10, dtype=np.uint8))
            effect.close()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].shape, (480, 640, 3))
        self.assertEqual(int(seen[0][240, 320, 0]), 10)
        self.assertTrue(np.all(result == 60))
        detector.close.assert_called_once()
        tracker.close.assert_called_once()
        background.close.assert_called_once()

    def test_tracking_initialization_failure_closes_background_once(self):
        from webcam_mods.effects import ProfileEffect
        from webcam_mods.settings import StartupSettings

        for stage in ("detector", "tracker"):
            with self.subTest(stage=stage):
                background, detector = Mock(), Mock()
                with (
                    patch(
                        "webcam_mods.entry.BackgroundEffect", return_value=background
                    ),
                    patch(
                        "webcam_mods.mods.mp_face.FaceDetector",
                        side_effect=(
                            RuntimeError("detector") if stage == "detector" else None
                        ),
                        return_value=detector,
                    ),
                    patch(
                        "webcam_mods.mods.camera_motion.CropTracker",
                        side_effect=RuntimeError("tracker"),
                    ),
                ):
                    with self.assertRaises(RuntimeError):
                        ProfileEffect(
                            Profile(effect="blur", track=True), StartupSettings()
                        )
                background.close.assert_called_once()
                if stage == "tracker":
                    detector.close.assert_called_once()
