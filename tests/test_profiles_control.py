from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.control import Controller
from webcam_mods.profiles import Profile, ProfileStore


class ProfileTests(unittest.TestCase):
    def test_starter_profiles_persist_without_overwriting_edits_or_deletions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.db"
            store = ProfileStore(path)
            store.save("Natural", {"brightness": 20})
            store.save("My Call", {"effect": "blur"})
            controller = Controller(store, lambda _: None)
            self.assertTrue(controller.dispatch("profiles.seed_defaults", {}))
            self.assertEqual(len(store.list()), 6)
            self.assertEqual(store.get("Natural").brightness, 20)
            self.assertEqual(store.get("Soft Background Blur").effect, "blur")
            self.assertTrue(store.get("Auto Framing").track)
            combined = store.get("Blur + Auto Framing")
            self.assertEqual(combined.effect, "blur")
            self.assertTrue(combined.track)
            self.assertEqual(combined.fps, 30)
            self.assertEqual(combined.processing_fps, 30)
            self.assertEqual(store.get("Studio Gray").effect, "color")
            store.save("Studio Gray", {"color": 100, "effect": "color"})
            store.delete("Auto Framing")
            reopened = ProfileStore(path)
            reopened.seed_defaults()
            self.assertEqual(reopened.get("Studio Gray").color, 100)
            self.assertNotIn("Auto Framing", [p["name"] for p in reopened.list()])
            self.assertEqual(reopened.get("My Call").effect, "blur")

    def test_seed_defaults_rejects_params_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            controller = Controller(store, lambda _: None)
            with self.assertRaisesRegex(ValueError, "params must be empty"):
                controller.dispatch("profiles.seed_defaults", {"unexpected": True})
            self.assertEqual(store.list(), [])

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
            camera = Mock(
                input_index=3, excluded_reason=None, device_id="physical-input"
            )
            camera.name = "Input"
            with (
                patch("webcam_mods.control.sys.platform", "darwin"),
                patch(
                    "webcam_mods.macos.capture.camera_inventory", return_value=[camera]
                ) as inventory,
            ):
                self.assertEqual(
                    controller.dispatch("cameras.list", {"capture": "auto"}),
                    [{"index": 3, "name": "Input", "id": "physical-input"}],
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


class ProfileCaptureSettingsTests(unittest.TestCase):
    def test_optional_settings_validate_without_coercion(self):
        for key, values in {
            "camera_id": ["", " ", 1, "bad\nidentity"],
            "output_width": [True, 15, 8193, 640.0],
            "output_height": [False, 0, "480"],
            "output_fps": [True, 0, 241, float("nan"), "30"],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    Profile.parse({key: value})
        self.assertEqual(Profile.parse({}), Profile())

    def test_saved_camera_tracks_reordering_and_rejects_missing_or_excluded(self):
        from webcam_mods.capture import camera_index_for_id
        from webcam_mods.macos.capture import CameraInfo

        wanted = CameraInfo(4, "Physical", (), device_id="physical")
        other = CameraInfo(0, "Other", (), device_id="other")
        excluded = CameraInfo(None, "OBS", (), "OBS output", "physical")
        with patch("webcam_mods.capture.sys.platform", "darwin"):
            for inventory, expected in (
                ([other, wanted], 4),
                ([CameraInfo(1, "Physical", (), device_id="physical"), other], 1),
            ):
                with patch(
                    "webcam_mods.macos.capture.camera_inventory", return_value=inventory
                ) as listing:
                    self.assertEqual(
                        camera_index_for_id("physical", "opencv"), expected
                    )
                    listing.assert_called_once_with("opencv")
            for inventory, message in (
                ([other], "no longer available"),
                ([excluded], "OBS output"),
                (
                    [CameraInfo(2, "Physical", (), "lid closed", "physical")],
                    "lid closed",
                ),
            ):
                with patch(
                    "webcam_mods.macos.capture.camera_inventory", return_value=inventory
                ):
                    with self.assertRaisesRegex(ValueError, message):
                        camera_index_for_id("physical", "auto")

    def test_profile_settings_separate_capture_and_output_and_keep_legacy_defaults(
        self,
    ):
        from webcam_mods.control import run_profile

        for profile, expected in (
            (Profile(width=1280, height=720, fps=60), (1280, 720, 60)),
            (
                Profile(
                    width=1280,
                    height=720,
                    fps=60,
                    output_width=640,
                    output_height=480,
                    output_fps=30,
                    camera_id="physical",
                ),
                (640, 480, 30),
            ),
        ):
            with (
                self.subTest(profile=profile),
                patch(
                    "webcam_mods.capture.camera_index_for_id", return_value=5
                ) as resolve,
                patch(
                    "webcam_mods.capture.create_camera", return_value=Mock()
                ) as camera,
                patch(
                    "webcam_mods.effects.ProfileEffect", return_value=Mock()
                ) as effect,
                patch("webcam_mods.loopback.live_loop") as loop,
            ):
                run_profile(
                    profile, threading.Event(), lambda: None, lambda source: None
                )
                settings = camera.call_args.args[0]
                self.assertEqual(
                    camera.call_args.kwargs["device_id"], profile.camera_id
                )
                self.assertEqual(
                    (settings.in_width, settings.in_height, settings.in_fps),
                    (1280, 720, 60),
                )
                self.assertEqual(
                    (settings.out_width, settings.out_height, settings.max_out_fps),
                    expected,
                )
                self.assertIs(effect.call_args.args[1], settings)
                self.assertIs(loop.call_args.kwargs["settings"], settings)
                if profile.camera_id:
                    resolve.assert_called_once_with("physical", "auto")
                    self.assertEqual(settings.video_in, 5)
                else:
                    resolve.assert_not_called()
                    self.assertEqual(settings.video_in, 0)

    def test_optional_settings_sqlite_roundtrip_and_old_json_defaults(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save(
                "new", {"camera_id": "physical", "output_width": 640, "output_fps": 15}
            )
            self.assertEqual(store.get("new").camera_id, "physical")
            self.assertEqual(store.get("new").output_width, 640)
            self.assertEqual(store.get("new").output_fps, 15)
            from contextlib import closing

            with closing(sqlite3.connect(store.path)) as db, db:
                db.execute(
                    "INSERT INTO profiles VALUES (?, ?)",
                    ("old", '{"width":1280,"height":720}'),
                )
            self.assertIsNone(store.get("old").camera_id)
            self.assertIsNone(store.get("old").output_width)


class BoundedControlProtocolTests(unittest.TestCase):
    def test_oversized_and_nonfinite_requests_recover_before_next_valid_request(self):
        import json
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-m", "webcam_mods.control"],
                input="x" * 65537
                + '\n{"id":2,"method":"status","params":{"fps":NaN}}\n{"id":3,"method":"hello"}\n{"id":4,"method":"status"}\n',
                text=True,
                capture_output=True,
                env={**os.environ, "XDG_CONFIG_HOME": directory},
                timeout=10,
                check=True,
            )
            replies = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(replies), 4)
            self.assertIn("64 KiB", replies[0]["error"])
            self.assertIn("error", replies[1])
            self.assertEqual(replies[2]["result"]["protocol"], 1)
            self.assertEqual(replies[3]["result"], {"state": "idle"})


class ProfileAcquisitionIdentityTests(unittest.TestCase):
    def test_saved_identity_reaches_native_adapter_without_reenumerating_index(self):
        from webcam_mods.capture import create_camera
        from webcam_mods.settings import StartupSettings

        for backend in ("auto", "avfoundation"):
            with (
                self.subTest(backend=backend),
                patch(
                    "webcam_mods.capture.resolve_backend", return_value="avfoundation"
                ),
                patch(
                    "webcam_mods.capture.opencv_device_id", return_value="wrong-camera"
                ) as mapping,
                patch("webcam_mods.macos.capture.AVFoundationCamera") as native,
            ):
                create_camera(
                    StartupSettings(video_in=4), backend, device_id="saved-camera"
                )
                mapping.assert_not_called()
                self.assertEqual(native.call_args.kwargs["device_id"], "saved-camera")
                self.assertEqual(native.call_args.kwargs["device_index"], 4)


class ProfileRecoveryTests(unittest.TestCase):
    def test_corrupt_record_does_not_hide_valid_profiles_and_diagnostics_are_safe(self):
        from contextlib import closing
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save("valid", {"brightness": 20})
            with closing(sqlite3.connect(store.path)) as db, db:
                db.executemany(
                    "INSERT INTO profiles VALUES (?, ?)",
                    [
                        ("damaged-json", "private-corrupt-contents"),
                        ("damaged-config", '{"private_unknown_field": 42}'),
                    ],
                )
            valid, errors = store.list_with_errors()
            self.assertEqual([row["name"] for row in valid], ["valid"])
            self.assertEqual(store.list(), valid)
            self.assertEqual(store.errors(), errors)
            self.assertEqual(
                errors,
                [
                    {"name": "damaged-config", "error": "invalid profile settings"},
                    {"name": "damaged-json", "error": "invalid profile JSON"},
                ],
            )
            for name, message in (
                ("damaged-json", "invalid profile JSON"),
                ("damaged-config", "invalid profile settings"),
            ):
                with (
                    self.subTest(name=name),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    store.export(name, Path(directory) / "invalid-export.json")
            self.assertFalse((Path(directory) / "invalid-export.json").exists())
            store.delete("damaged-json")
            self.assertEqual(
                [row["name"] for row in store.errors()], ["damaged-config"]
            )
            self.assertEqual(store.get("valid").brightness, 20)

    def test_export_preserves_existing_target_until_explicit_overwrite(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ProfileStore(root / "profiles.db")
            store.save("valid", {"camera_id": "physical", "output_width": 1280})
            target = root / "backup.json"
            target.write_text("existing content")
            with self.assertRaises(FileExistsError):
                store.export("valid", target)
            self.assertEqual(target.read_text(), "existing content")
            store.export("valid", target, overwrite=True)
            self.assertEqual(
                Profile.parse(json.loads(target.read_text())), store.get("valid")
            )
            second = root / "new.json"
            store.export("valid", second)
            self.assertEqual(second.read_text(), target.read_text())
            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["backup.json", "new.json", "profiles.db"],
            )

    def test_cli_export_delete_and_named_corruption_warning(self):
        from contextlib import closing
        import json
        import sqlite3
        from typer.testing import CliRunner
        from webcam_mods.entry import app

        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save("kept", {"effect": "blur"})
            store.save("removed", {})
            with closing(sqlite3.connect(store.path)) as db, db:
                db.execute(
                    "INSERT INTO profiles VALUES (?, ?)", ("damaged", "not-json")
                )
            with patch("webcam_mods.profiles.ProfileStore", return_value=store):
                runner = CliRunner()
                listed = runner.invoke(app, ["profiles-list"])
                self.assertEqual(listed.exit_code, 0, listed.output)
                self.assertEqual(
                    [row["name"] for row in json.loads(listed.stdout)],
                    ["kept", "removed"],
                )
                self.assertIn("damaged: invalid profile JSON", listed.stderr)
                target = Path(directory) / "profile.json"
                exported = runner.invoke(app, ["profile-export", "kept", str(target)])
                self.assertEqual(exported.exit_code, 0, exported.output)
                previous = target.read_text()
                rejected = runner.invoke(
                    app, ["profile-export", "removed", str(target)]
                )
                self.assertEqual(rejected.exit_code, 2, rejected.output)
                self.assertEqual(target.read_text(), previous)
                overwritten = runner.invoke(
                    app, ["profile-export", "removed", str(target), "--overwrite"]
                )
                self.assertEqual(overwritten.exit_code, 0, overwritten.output)
                deleted = runner.invoke(app, ["profile-delete", "removed"])
                self.assertEqual(deleted.exit_code, 0, deleted.output)
                self.assertEqual([row["name"] for row in store.list()], ["kept"])
                missing = runner.invoke(app, ["profile-delete", "missing"])
                self.assertEqual(missing.exit_code, 2, missing.output)


class StoredProfileBoundsTests(unittest.TestCase):
    def test_deep_oversized_and_overflow_rows_are_isolated_and_sanitized(self):
        from contextlib import closing
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save("valid", {})
            bad = {
                "deep": ("[" * 2000 + "0" + "]" * 2000, "invalid profile settings"),
                "oversized": (
                    '"' + "private" * 10000 + '"',
                    "profile config exceeds 64 KiB limit",
                ),
                "unicode-oversized": (
                    '"' + "é" * 33000 + '"',
                    "profile config exceeds 64 KiB limit",
                ),
                "overflow": ('{"fps":' + "9" * 400 + "}", "invalid profile settings"),
            }
            with closing(sqlite3.connect(store.path)) as db, db:
                db.executemany(
                    "INSERT INTO profiles VALUES (?, ?)",
                    [(name, config) for name, (config, _) in bad.items()],
                )
            valid, errors = store.list_with_errors()
            self.assertEqual([row["name"] for row in valid], ["valid"])
            self.assertEqual(
                {row["name"]: row["error"] for row in errors},
                {name: error for name, (_, error) in bad.items()},
            )
            for name, (_, message) in bad.items():
                with (
                    self.subTest(name=name),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    store.get(name)

    def test_large_integer_rate_is_rejected_as_value_error(self):
        for key in ("fps", "processing_fps", "output_fps"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "finite"):
                Profile.parse({key: 10**400})

    def test_decoder_recursion_failure_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProfileStore(Path(directory) / "profiles.db")
            store.save("fixture", {})
            with patch(
                "webcam_mods.profiles.json.loads",
                side_effect=RecursionError("private corrupt data"),
            ):
                self.assertEqual(
                    store.errors(),
                    [{"name": "fixture", "error": "invalid profile JSON"}],
                )
                with self.assertRaisesRegex(ValueError, "invalid profile JSON"):
                    store.get("fixture")
