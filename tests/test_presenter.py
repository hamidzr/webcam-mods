"""Presenter overlay: the camera as a bubble or cutout over a shared screen."""

import threading
import time
from typing import Any
import unittest
from unittest.mock import Mock, patch

import numpy as np

from webcam_mods.control import run_profile
from webcam_mods.effects import ProfileEffect
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.input.presenter import CameraFeed, PresenterInput
from webcam_mods.input.screen import Screen
from webcam_mods.mods.presenter import bubble, circle_alpha, cutout, place
from webcam_mods.profiles import RESTART_FIELDS, Profile
from webcam_mods.settings import StartupSettings
from webcam_mods.utils.video import Frame

WIDTH, HEIGHT = 160, 90
SCREEN = 100
RED = (0, 0, 255)


def screen_frame() -> Frame:
    return np.full((HEIGHT, WIDTH, 3), SCREEN, np.uint8)


def red_camera() -> Frame:
    camera = np.zeros((48, 64, 3), np.uint8)
    camera[:] = RED
    return camera


class FakeCamera(FrameInput):
    def __init__(self, *, fail_setup: bool = False, fail_read: bool = False) -> None:
        super().__init__(width=64, height=48, fps=30, device="fake")
        self.fail_setup, self.fail_read = fail_setup, fail_read
        self.open = False
        self.threads: list[str] = []

    def setup(self) -> AdapterMetadata:
        self.threads.append(threading.current_thread().name)
        if self.fail_setup:
            raise RuntimeError("camera busy")
        self.open = True
        return {"width": 64, "height": 48, "fps": 30}

    def frame(self) -> Frame | None:
        time.sleep(0.005)
        if self.fail_read:
            raise RuntimeError("camera unplugged")
        return red_camera()

    def teardown(self, *args: Any, **kwargs: Any) -> None:
        self.threads.append(threading.current_thread().name)
        self.open = False

    def is_setup(self) -> bool:
        return self.open


def wait_for(condition: Any) -> None:
    deadline = time.monotonic() + 2
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.005)


class PresenterProfileTests(unittest.TestCase):
    def test_fields_are_validated_and_only_the_switch_restarts(self) -> None:
        profile = Profile.parse(
            {
                "source": "screen",
                "screen_region": [0, 0, 1280, 720],
                "presenter": True,
                "presenter_style": "cutout",
                "presenter_position": "bottom-left",
                "presenter_size": 50,
            }
        )
        self.assertTrue(profile.presenting)
        # kept while the camera is the source, so switching back keeps the choice
        self.assertFalse(Profile(presenter=True).presenting)
        for bad in (
            {"presenter": "bubble"},
            {"presenter_style": "square"},
            {"presenter_position": "middle"},
            {"presenter_size": 9},
            {"presenter_size": 81},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Profile.parse(bad)
        self.assertIn("presenter", RESTART_FIELDS)
        self.assertFalse(
            {"presenter_style", "presenter_position", "presenter_size"} & RESTART_FIELDS
        )


class LayerTests(unittest.TestCase):
    def test_bubble_is_the_middle_square_in_a_disc(self) -> None:
        camera = np.zeros((40, 80, 3), np.uint8)
        camera[:, 20:60] = 200
        layer, alpha = bubble(camera, 20)
        self.assertEqual(layer.shape, (20, 20, 3))
        self.assertTrue(np.all(layer == 200))
        self.assertEqual(alpha.shape, (20, 20, 1))
        self.assertEqual(float(alpha[0, 0, 0]), 0)
        self.assertEqual(float(alpha[10, 10, 0]), 1)
        self.assertIs(circle_alpha(20), circle_alpha(20))

    def test_cutout_keeps_aspect_and_mask(self) -> None:
        image = np.full((48, 64, 3), 50, np.uint8)
        # segmentation never quite reaches 0 or 1; near values snap
        mask = np.full((48, 64, 1), 0.0067, np.float32)
        mask[:, 32:] = 0.9933
        layer, alpha = cutout(image, mask, 24)
        self.assertEqual((layer.shape, alpha.shape), ((24, 32, 3), (24, 32, 1)))
        self.assertEqual(float(alpha[12, 2, 0]), 0)
        self.assertEqual(float(alpha[12, 30, 0]), 1)

    def test_place_uses_corners_and_stands_cutouts_on_the_bottom(self) -> None:
        frame = screen_frame()
        layer = np.full((20, 20, 3), 255, np.uint8)
        alpha = np.ones((20, 20, 1), np.float32)
        margin = round(0.03 * HEIGHT)
        for position, (row, column) in (
            ("top-left", (margin, margin)),
            ("top-right", (margin, WIDTH - margin - 20)),
            ("bottom-left", (HEIGHT - margin - 20, margin)),
            ("bottom-right", (HEIGHT - margin - 20, WIDTH - margin - 20)),
        ):
            with self.subTest(position=position):
                out = place(frame, layer, alpha, position, standing=False)
                rows, columns = np.nonzero(out[:, :, 0] == 255)
                self.assertEqual((rows.min(), columns.min()), (row, column))
        standing = place(frame, layer, alpha, "top-left", standing=True)
        self.assertTrue(np.all(standing[HEIGHT - 1, margin : margin + 20] == 255))
        np.testing.assert_array_equal(frame, screen_frame())
        # oversized layers are cut at the frame edge
        huge = np.full((200, 300, 3), 255, np.uint8)
        out = place(
            frame, huge, np.ones((200, 300, 1), np.float32), "top-left", standing=False
        )
        self.assertEqual(out.shape, frame.shape)


class PresenterEffectTests(unittest.TestCase):
    def effect(self, **fields: Any) -> ProfileEffect:
        profile = Profile(
            source="screen",
            screen_region=(0, 0, WIDTH, HEIGHT),
            presenter=True,
            **fields,
        )
        effect = ProfileEffect(
            profile, StartupSettings(out_width=WIDTH, out_height=HEIGHT)
        )
        self.addCleanup(effect.close)
        return effect

    def test_bubble_shows_the_graded_camera_and_leaves_the_screen_alone(self) -> None:
        effect = self.effect(presenter_size=40, brightness=40, mirror=True)
        out = effect(screen_frame())
        assert out is not None
        # no camera frame yet: the screen alone
        np.testing.assert_array_equal(out, screen_frame())
        camera = np.full((48, 64, 3), (0, 0, 150), np.uint8)
        effect.camera_feed = lambda: camera
        out = effect(screen_frame())
        assert out is not None
        diameter = round(HEIGHT * 0.4)
        margin = round(0.03 * HEIGHT)
        center = (HEIGHT - margin - diameter // 2, WIDTH - margin - diameter // 2)
        # brightness applies to the camera, never to the shared screen
        self.assertEqual(tuple(out[center]), (0, 0, 190))
        np.testing.assert_array_equal(out[:20, :20], screen_frame()[:20, :20])
        np.testing.assert_array_equal(
            out[HEIGHT - 2, WIDTH - margin - diameter], screen_frame()[0, 0]
        )
        layer = effect._presented
        effect(screen_frame())
        self.assertIs(effect._presented, layer)
        effect.update(
            Profile(
                source="screen",
                screen_region=(0, 0, WIDTH, HEIGHT),
                presenter=True,
                presenter_position="top-left",
            )
        )
        out = effect(screen_frame())
        assert out is not None
        self.assertEqual(tuple(out[margin + 5, margin + diameter // 2]), (0, 0, 150))

    def test_screen_skips_orientation_and_background_effects(self) -> None:
        screen = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        screen[:, : WIDTH // 2] = 255
        with patch("webcam_mods.mods.person_segmentation.MediaPipeSegmenter") as model:
            effect = self.effect(mirror=True, effect="blur", track=True)
            out = effect(screen)
        model.assert_not_called()
        self.assertIsNone(effect.tracking)
        np.testing.assert_array_equal(out, screen)

    def test_cutout_places_the_person_on_the_bottom_edge(self) -> None:
        segmenter = Mock()

        def person(image: Frame) -> np.ndarray:
            mask = np.zeros(image.shape[:2], np.float32)
            mask[:, 24:40] = 1
            return mask

        segmenter.predict.side_effect = person
        with patch(
            "webcam_mods.mods.person_segmentation.MediaPipeSegmenter",
            return_value=segmenter,
        ):
            effect = self.effect(presenter_style="cutout", presenter_size=60)
            camera = red_camera()
            effect.camera_feed = lambda: camera
            out = effect(screen_frame())
        assert out is not None
        red = (out[:, :, 2] > 200) & (out[:, :, 0] < 60)
        rows, columns = np.nonzero(red)
        self.assertEqual(rows.max(), HEIGHT - 1)
        self.assertGreater(columns.min(), WIDTH // 2)
        # the camera picture around the person stays transparent
        self.assertLess(red.sum(), 0.6 * round(HEIGHT * 0.6) * 72)
        effect.update(
            Profile(
                source="screen", screen_region=(0, 0, WIDTH, HEIGHT), presenter=True
            )
        )
        effect(screen_frame())
        self.assertIsNone(effect.presenter_effects)
        segmenter.close.assert_called_once()


class CameraFeedTests(unittest.TestCase):
    def test_camera_runs_on_its_own_thread_and_stops(self) -> None:
        camera = FakeCamera()
        feed = CameraFeed(camera)
        feed.start()
        self.addCleanup(feed.stop)
        wait_for(lambda: feed.latest() is not None)
        feed.stop()
        self.assertFalse(camera.open)
        self.assertEqual(camera.threads, ["webcam-presenter-camera"] * 2)
        # restartable after a pause
        feed.start()
        self.assertTrue(camera.open)
        feed.stop()

    def test_setup_and_read_failures_surface(self) -> None:
        feed = CameraFeed(FakeCamera(fail_setup=True))
        with self.assertRaisesRegex(RuntimeError, "camera busy"):
            feed.start()
        feed = CameraFeed(FakeCamera(fail_read=True))
        feed.start()
        self.addCleanup(feed.stop)

        def failed() -> bool:
            try:
                feed.latest()
            except RuntimeError as error:
                self.assertIn("camera unplugged", str(error))
                return True
            return False

        wait_for(failed)

    def test_presenter_input_opens_and_closes_both(self) -> None:
        screen = Mock(width=WIDTH, height=HEIGHT, fps=30, device=None)
        screen.setup.return_value = {"width": WIDTH, "height": HEIGHT, "fps": 30}
        screen.frame.return_value = screen_frame()
        camera = FakeCamera()
        source = PresenterInput(screen, CameraFeed(camera))
        self.assertEqual(source.setup()["width"], WIDTH)
        self.assertTrue(camera.open)
        np.testing.assert_array_equal(source.frame(), screen_frame())
        source.teardown()
        self.assertFalse(camera.open)
        screen.teardown.assert_called_once()
        failing = PresenterInput(screen, CameraFeed(FakeCamera(fail_setup=True)))
        with self.assertRaisesRegex(RuntimeError, "camera busy"):
            failing.setup()
        self.assertEqual(screen.teardown.call_count, 2)


class PresenterSessionTests(unittest.TestCase):
    def test_run_profile_opens_the_saved_camera_beside_the_screen(self) -> None:
        profile = Profile(
            source="screen",
            screen_region=(0, 0, 1280, 720),
            presenter=True,
            camera_id="desk-camera",
            width=1920,
            height=1080,
        )
        with (
            patch("webcam_mods.capture.camera_index_for_id", return_value=2) as lookup,
            patch("webcam_mods.capture.create_camera") as camera,
            patch("webcam_mods.loopback.live_loop") as loop,
        ):
            run_profile(profile, threading.Event(), lambda: None, lambda _: None)
        lookup.assert_called_once()
        camera_settings = camera.call_args.args[0]
        self.assertEqual(
            (
                camera_settings.in_width,
                camera_settings.in_height,
                camera_settings.video_in,
            ),
            (1920, 1080, 2),
        )
        self.assertEqual(camera.call_args.kwargs["device_id"], "desk-camera")
        source = loop.call_args.kwargs["fIn"]
        self.assertIsInstance(source, PresenterInput)
        self.assertIsInstance(source.screen, Screen)
        self.assertEqual(loop.call_args.kwargs["settings"].in_width, 1280)
        effect = loop.call_args.kwargs["mod"]
        self.assertEqual(effect.camera_feed, source.feed.latest)
        effect.close()


if __name__ == "__main__":
    unittest.main()
