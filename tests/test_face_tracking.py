"""Bounded face framing and time-based tracking regressions."""

import math
import unittest

from webcam_mods.geometry import Rect
from webcam_mods.mods.camera_motion import CropTracker
from webcam_mods.mods.mp_face import FaceSelector

FRAME = (1280, 720)


def face(height: int, x: int = 640, y: int = 300) -> Rect:
    return Rect(w=height, h=height, l=x - height // 2, t=y - height // 2)


def bounds(rect: Rect) -> tuple[int, int, int, int]:
    return rect.l, rect.t, rect.w, rect.h


class FaceTrackingTest(unittest.TestCase):
    def assert_valid_crop(
        self, crop: Rect, frame: tuple[int, int] = FRAME, aspect: float = 4 / 3
    ) -> None:
        self.assertGreater(crop.w, 0)
        self.assertGreater(crop.h, 0)
        self.assertGreaterEqual(crop.l, 0)
        self.assertGreaterEqual(crop.t, 0)
        self.assertLessEqual(crop.l + crop.w, frame[0])
        self.assertLessEqual(crop.t + crop.h, frame[1])
        self.assertLessEqual(abs(crop.w - crop.h * aspect), 2)

    def test_first_face_frames_immediately_at_target_proportion(self) -> None:
        tracker = CropTracker()
        pred = face(160)
        crop = tracker.generate_crop(pred, frame_size=FRAME, now=0)
        self.assert_valid_crop(crop)
        self.assertAlmostEqual(pred.h / crop.h, 0.4, delta=0.005)
        self.assertAlmostEqual((pred.center.l - crop.l) / crop.w, 0.5, delta=0.005)
        self.assertAlmostEqual((pred.center.t - crop.t) / crop.h, 0.42, delta=0.005)

    def test_distance_changes_adjust_zoom_in_both_directions(self) -> None:
        tracker = CropTracker(max_zoom=4)
        start = tracker.generate_crop(face(160), frame_size=FRAME, now=0)
        for index in range(1, 51):
            farther = tracker.generate_crop(face(80), frame_size=FRAME, now=index / 10)
        for index in range(51, 101):
            closer = tracker.generate_crop(face(240), frame_size=FRAME, now=index / 10)
        self.assertLess(farther.h, start.h)
        self.assertGreater(closer.h, start.h)
        self.assertAlmostEqual(farther.h, 200, delta=2)
        self.assertAlmostEqual(closer.h, 600, delta=2)

    def test_sideways_motion_does_not_activate_subthreshold_zoom(self) -> None:
        tracker = CropTracker(max_zoom=4)
        start = tracker.generate_crop(face(160), frame_size=FRAME, now=0)
        for index in range(1, 51):
            moved = tracker.generate_crop(
                face(155, x=840), frame_size=FRAME, now=index / 10
            )
        self.assertGreater(moved.l, start.l)
        self.assertEqual((moved.w, moved.h), (start.w, start.h))

    def test_tiny_face_cannot_exceed_zoom_cap(self) -> None:
        for height in (1, 10, 20):
            with self.subTest(height=height):
                crop = CropTracker(max_zoom=2).generate_crop(
                    face(height), frame_size=FRAME, now=0
                )
                self.assert_valid_crop(crop)
                self.assertGreaterEqual(crop.h, 360)
                self.assertGreaterEqual(crop.w, 480)

    def test_near_face_uses_largest_fitted_view(self) -> None:
        crop = CropTracker().generate_crop(face(600), frame_size=FRAME, now=0)
        self.assert_valid_crop(crop)
        self.assertEqual((crop.w, crop.h), (960, 720))

    def test_output_aspect_and_zoom_cap_use_fitted_frame(self) -> None:
        crop = CropTracker(aspect_ratio=16 / 9).generate_crop(
            face(5), frame_size=FRAME, now=0
        )
        self.assert_valid_crop(crop, aspect=16 / 9)
        self.assertEqual((crop.w, crop.h), (640, 360))

    def test_edge_faces_keep_crop_inside_camera(self) -> None:
        for x, y in ((0, 0), (1280, 0), (0, 720), (1280, 720)):
            with self.subTest(x=x, y=y):
                crop = CropTracker().generate_crop(
                    face(100, x=x, y=y), frame_size=FRAME, now=0
                )
                self.assert_valid_crop(crop)

    def test_frame_resize_resets_incompatible_crop_immediately(self) -> None:
        tracker = CropTracker()
        tracker.generate_crop(face(160, x=1100), frame_size=FRAME, now=0)
        small_frame = (320, 240)
        crop = tracker.generate_crop(
            face(30, x=160, y=100), frame_size=small_frame, now=0.01
        )
        fresh = CropTracker().generate_crop(
            face(30, x=160, y=100), frame_size=small_frame, now=0.01
        )
        self.assert_valid_crop(crop, frame=small_frame)
        self.assertEqual(bounds(crop), bounds(fresh))

    def test_position_and_size_jitter_do_not_move_crop(self) -> None:
        tracker = CropTracker(max_zoom=4)
        initial = tracker.generate_crop(face(160), frame_size=FRAME, now=0)
        for index, (height, x, y) in enumerate(
            ((161, 645, 305), (158, 635, 296), (164, 650, 302)), start=1
        ):
            crop = tracker.generate_crop(
                face(height, x=x, y=y), frame_size=FRAME, now=index / 10
            )
            self.assertEqual(bounds(crop), bounds(initial))

    def test_deadzone_is_anchored_so_slow_drift_eventually_tracks(self) -> None:
        tracker = CropTracker(max_zoom=4)
        initial = tracker.generate_crop(face(160), frame_size=FRAME, now=0)
        for index in range(1, 31):
            crop = tracker.generate_crop(
                face(160, x=640 + index * 4), frame_size=FRAME, now=index / 10
            )
        self.assertGreater(crop.l, initial.l + 30)

    def test_smoothing_depends_on_elapsed_time_not_frame_count(self) -> None:
        def run(steps: int) -> Rect:
            tracker = CropTracker(max_zoom=4)
            tracker.generate_crop(face(160), frame_size=FRAME, now=0)
            for index in range(1, steps + 1):
                crop = tracker.generate_crop(
                    face(220, x=800), frame_size=FRAME, now=index / steps
                )
            return crop

        sparse, dense = run(10), run(100)
        for a, b in zip(bounds(sparse), bounds(dense)):
            self.assertAlmostEqual(a, b, delta=2)

    def test_face_loss_holds_then_smoothly_returns_to_wide_frame(self) -> None:
        tracker = CropTracker()
        initial = tracker.generate_crop(face(100, x=400), frame_size=FRAME, now=0)
        held = tracker.generate_crop(None, frame_size=FRAME, now=0.5)
        self.assertEqual(bounds(held), bounds(initial))
        widening = tracker.generate_crop(None, frame_size=FRAME, now=1.1)
        self.assertGreater(widening.h, initial.h)
        self.assertLess(widening.h, 720)
        wide = tracker.generate_crop(None, frame_size=FRAME, now=10)
        self.assertAlmostEqual(wide.h, 720, delta=1)
        self.assertAlmostEqual(wide.l, 160, delta=1)
        self.assertAlmostEqual(wide.t, 0, delta=1)

    def test_reacquisition_resumes_tracking_after_loss(self) -> None:
        tracker = CropTracker()
        tracker.generate_crop(face(100), frame_size=FRAME, now=0)
        tracker.generate_crop(None, frame_size=FRAME, now=10)
        recovered = tracker.generate_crop(face(160), frame_size=FRAME, now=15)
        self.assertAlmostEqual(recovered.h, 400, delta=2)
        self.assert_valid_crop(recovered)

    def test_missing_initial_face_returns_centered_wide_frame(self) -> None:
        crop = CropTracker().generate_crop(None, frame_size=FRAME, now=0)
        self.assertEqual(bounds(crop), (160, 0, 960, 720))

    def test_invalid_configuration_rejected(self) -> None:
        settings = (
            {"fps": 0},
            {"fps": math.inf},
            {"aspect_ratio": 0},
            {"aspect_ratio": math.nan},
            {"face_height": 0},
            {"face_height": 1.1},
            {"max_zoom": 0.9},
            {"max_zoom": math.inf},
            {"target_x": -0.1},
            {"target_y": 1.1},
            {"pan_deadzone": -0.1},
            {"zoom_deadzone": -0.1},
            {"pan_seconds": -1},
            {"zoom_seconds": math.nan},
            {"lost_after": -1},
        )
        for kwargs in settings:
            with self.subTest(settings=kwargs), self.assertRaises(ValueError):
                CropTracker(**kwargs)


class FaceSelectorTest(unittest.TestCase):
    def test_rejects_invalid_time_without_poisoning_selection(self) -> None:
        selector = FaceSelector()
        selector.select([face(100, x=300)], FRAME, now=1)
        for now in (float("nan"), float("inf"), 0):
            with self.subTest(now=now), self.assertRaises(ValueError):
                selector.select([], FRAME, now=now)
        replacement = face(100, x=1000)
        selected = selector.select([replacement], FRAME, now=3)
        self.assertEqual(bounds(selected), bounds(replacement))

    def test_largest_initial_face_wins(self) -> None:
        selector = FaceSelector()
        large = face(160, x=250)
        selected = selector.select([face(100), large], FRAME, now=0)
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(large))

    def test_equal_size_faces_prefer_frame_center(self) -> None:
        selector = FaceSelector()
        centered = face(100, x=640, y=360)
        selected = selector.select([face(100, x=200), centered], FRAME, now=0)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(centered))

    def test_reordering_does_not_switch_to_larger_other_face(self) -> None:
        selector = FaceSelector()
        tracked = face(100, x=300)
        selector.select([tracked, face(80, x=900)], FRAME, now=0)
        selected = selector.select([face(160, x=900), tracked], FRAME, now=0.1)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(tracked))

    def test_nearest_same_scale_face_wins(self) -> None:
        selector = FaceSelector()
        selector.select([face(100, x=300)], FRAME, now=0)
        nearby = face(100, x=320)
        selected = selector.select([face(160, x=400), nearby], FRAME, now=0.1)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(nearby))

    def test_incompatible_face_size_rejected_during_hold(self) -> None:
        for height in (30, 300):
            with self.subTest(height=height):
                selector = FaceSelector()
                selector.select([face(100)], FRAME, now=0)
                self.assertIsNone(selector.select([face(height)], FRAME, now=0.1))

    def test_far_face_rejected_until_original_subject_times_out(self) -> None:
        selector = FaceSelector(lost_after=1)
        selector.select([face(100, x=300)], FRAME, now=0)
        replacement = face(180, x=900)
        self.assertIsNone(selector.select([replacement], FRAME, now=0.5))
        self.assertIsNone(selector.select([replacement], FRAME, now=0.9))
        selected = selector.select([face(100), replacement], FRAME, now=1.1)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(replacement))

    def test_empty_detection_keeps_subject_for_reacquisition(self) -> None:
        selector = FaceSelector()
        selector.select([face(100, x=300)], FRAME, now=0)
        self.assertIsNone(selector.select([], FRAME, now=0.5))
        reacquired = face(100, x=310)
        selected = selector.select([face(160, x=900), reacquired], FRAME, now=0.6)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(reacquired))

    def test_input_and_output_mutation_do_not_change_subject_state(self) -> None:
        selector = FaceSelector()
        original = face(100, x=300)
        selected = selector.select([original], FRAME, now=0)
        assert selected is not None
        original.left = 1000
        selected.left = 2000
        nearby = face(100, x=320)
        selected = selector.select([nearby], FRAME, now=0.1)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(nearby))

    def test_reset_allows_new_subject_immediately(self) -> None:
        selector = FaceSelector()
        selector.select([face(100, x=300)], FRAME, now=0)
        selector.reset()
        replacement = face(160, x=900)
        selected = selector.select([replacement], FRAME, now=0.1)
        assert selected is not None
        self.assertEqual(bounds(selected), bounds(replacement))


if __name__ == "__main__":
    unittest.main()
