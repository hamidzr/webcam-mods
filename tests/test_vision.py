"""Smoke tests for native MediaPipe vision tasks."""

import unittest

import numpy as np

from webcam_mods.mods import mp_face, person_segmentation


class VisionTasksTest(unittest.TestCase):
    def test_face_detector_processes_blank_frame(self) -> None:
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        self.assertIsNone(mp_face.predict(frame))

    def test_segmenter_processes_blank_frame(self) -> None:
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        image, mask = person_segmentation.mask(frame)
        self.assertEqual(image.shape, frame.shape)
        self.assertEqual(mask.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
