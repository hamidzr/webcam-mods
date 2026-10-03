"""Pixel geometry stays integral through crop arithmetic."""

import unittest

from webcam_mods.geometry import Point, Rect


class GeometryTests(unittest.TestCase):
    def test_float_divisor_preserves_integer_pixels_and_flooring(self) -> None:
        original = Point(t=-7, l=11)
        divided = original / 2.5
        self.assertEqual(divided.tuple, (4, -3))
        self.assertIs(type(divided.t), int)
        self.assertIs(type(divided.l), int)
        self.assertEqual(original.tuple, (11, -7))

    def test_point_comparison_handles_unrelated_types(self) -> None:
        self.assertFalse(Point() == None)
        self.assertFalse(Point() == (0, 0))
        self.assertTrue(Point(t=2, l=3) == Point(t=2, l=3))

    def test_rect_center_and_legacy_bounds_helper(self) -> None:
        rect = Rect(w=5, h=7, t=-3, l=4)
        self.assertEqual(rect.center, Point(t=0, l=6))
        self.assertEqual(
            rect.__dict__(), {"width": 5, "height": 7, "top": -3, "left": 4}
        )
        rect.center_on(Point(t=10, l=20))
        self.assertEqual(rect.center, Point(t=10, l=20))


if __name__ == "__main__":
    unittest.main()
