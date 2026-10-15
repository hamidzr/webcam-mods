"""Mirror flips source pixels once, before crop, effects and output sizing."""

import threading
from typing import Any
from unittest.mock import Mock, patch

import numpy as np
from typer.testing import CliRunner

from cli_fixtures import HeadlessCliTestCase

from webcam_mods import entry
from webcam_mods.input.input import AdapterMetadata, FrameInput, FrameOutput
from webcam_mods.loopback import live_loop
from webcam_mods.profiles import Profile
from webcam_mods.settings import StartupSettings, load_settings
from webcam_mods.utils.video import Frame


class GradientSource(FrameInput):
    def __init__(self) -> None:
        super().__init__(width=32, height=24, fps=30, device="test")
        self.active = False
        # each column holds its own index, so a flip is visible in any row
        self.pixels = np.repeat(
            np.arange(32, dtype=np.uint8)[None, :, None], 24, axis=0
        ).repeat(3, axis=2)

    def setup(self) -> AdapterMetadata:
        self.active = True
        return {"width": 32, "height": 24, "fps": 30}

    def is_setup(self) -> bool:
        return self.active

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.active = False

    def frame(self) -> Frame:
        return self.pixels.copy()


class RecordingOutput(FrameOutput):
    def __init__(self) -> None:
        super().__init__(width=32, height=24, fps=30, device="test")
        self.active = False
        self.frames: list[Frame] = []

    def setup(self) -> AdapterMetadata:
        self.active = True
        return {"width": self.width, "height": self.height, "fps": self.fps}

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.active = False

    def is_setup(self) -> bool:
        return self.active

    def send(self, frame: Frame) -> None:
        self.frames.append(frame.copy())


class MirrorTests(HeadlessCliTestCase):
    def test_loop_flips_input_before_mod_only_when_enabled(self) -> None:
        for mirror in (False, True):
            with self.subTest(mirror=mirror):
                source, output, seen = GradientSource(), RecordingOutput(), []

                def mod(frame: Frame) -> Frame:
                    seen.append(frame.copy())
                    return frame

                live_loop(
                    mod=mod,
                    fIn=source,
                    fOut=output,
                    interactive_listener=None,
                    settings=StartupSettings(
                        in_width=32,
                        in_height=24,
                        out_width=32,
                        out_height=24,
                        mirror=mirror,
                    ),
                    on_demand=False,
                    max_frames=2,
                    pace=False,
                    strict_errors=True,
                )
                expected = source.pixels[:, ::-1] if mirror else source.pixels
                self.assertEqual(len(output.frames), 2)
                for frame in (*seen, *output.frames):
                    np.testing.assert_array_equal(frame, expected)

    def test_profile_env_and_cli_resolve_mirror(self) -> None:
        self.assertFalse(Profile.parse({}).mirror)
        self.assertTrue(Profile.parse({"mirror": True}).mirror)
        with self.assertRaises(ValueError):
            Profile.parse({"mirror": "yes"})
        self.assertFalse(load_settings({}).mirror)
        self.assertTrue(load_settings({"MIRROR": "true"}).mirror)
        with self.assertRaises(ValueError):
            StartupSettings(mirror=1)  # type: ignore[arg-type]
        for arguments, expected in (
            (["--mirror", "test-loop"], True),
            (["test-loop", "--mirror"], True),
            (["--mirror", "test-loop", "--no-mirror"], False),
        ):
            with patch.object(entry, "live_loop") as loop:
                result = CliRunner().invoke(entry.app, ["--no-controls", *arguments])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIs(loop.call_args.kwargs["settings"].mirror, expected)

    def test_profile_mirror_reaches_loop_settings(self) -> None:
        from webcam_mods.control import run_profile

        with (
            patch("webcam_mods.capture.create_camera", return_value=Mock()),
            patch("webcam_mods.effects.ProfileEffect", return_value=Mock()),
            patch("webcam_mods.loopback.live_loop") as loop,
        ):
            run_profile(
                Profile(mirror=True), threading.Event(), lambda: None, lambda _: None
            )
        self.assertTrue(loop.call_args.kwargs["settings"].mirror)

    def test_screen_border_follows_mirrored_crop(self) -> None:
        from webcam_mods.input.screen import Screen
        from webcam_mods.session import Command

        screen = Screen(left=-100, top=20, width=32, height=24, fps=30)
        indicator = Mock()

        def loop(**kwargs: Any) -> None:
            session = kwargs["before_frame"].__self__
            session.submit(Command("resize", -8, -6))
            session.submit(Command("move", 1, 3))
            kwargs["before_frame"]()
            kwargs["mod"](np.zeros((24, 32, 3), dtype=np.uint8))

        with patch.object(entry, "live_loop", side_effect=loop):
            entry._run(
                entry.Common(controls=False, settings=StartupSettings(mirror=True)),
                source=screen,
                border=indicator,
            )
        region = indicator.update.call_args.args[0]
        # crop starts 1 px from the mirrored left edge, so 7 px from the real one
        self.assertEqual((region.l, region.w), (-93, 24))
