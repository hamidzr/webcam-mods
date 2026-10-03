"""Interactive developer demo of face-crop interpolation."""

import cv2
import numpy as np

from webcam_mods.geometry import Point, Rect
from webcam_mods.mods.camera_motion import CropTracker
from webcam_mods.utils.video import sleep_until_fps


class Simulation:
    def __init__(self, fps: float | None = None) -> None:
        self.clicks = 0
        self.clicked = Point()
        self.tracker = CropTracker(fps)

    def click_handler(
        self, event: int, x: int, y: int, flags: int, data: object
    ) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.clicked = Point(t=y, l=x)
            self.clicks += 1

    def generate_prediction(self) -> Rect:
        size = 150 if self.clicks % 3 == 0 else 100
        prediction = Rect(w=size, h=size)
        prediction.center_on(self.clicked)
        return prediction

    def visualize(
        self,
        frame: Rect | None = None,
        crop: Rect | None = None,
        pred: Rect | None = None,
    ) -> None:
        frame = frame if frame is not None else Rect(w=400, h=400)
        crop = crop if crop is not None else Rect()
        pred = pred if pred is not None else Rect()
        image = np.zeros((frame.h, frame.w, 3), np.uint8)
        window_name = "simulate"
        cv2.namedWindow(window_name)
        cv2.setMouseCallback(window_name, self.click_handler)
        image = cv2.rectangle(
            image, pred.start_point.tuple, pred.end_point.tuple, (0, 255, 0), -1
        )
        image = cv2.rectangle(
            image, crop.start_point.tuple, crop.end_point.tuple, (255, 255, 255), 1
        )
        cv2.imshow(window_name, image)

    def run(self) -> None:
        print("click on the canvas to simulate moving the prediction box")
        try:
            while True:
                pred = self.generate_prediction()
                crop = self.tracker.generate_crop(
                    pred, padding=None, frame_size=(400, 400)
                )
                self.visualize(pred=pred, crop=crop)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
                sleep_until_fps(self.tracker.fps)
        finally:
            self.tracker.close()
            cv2.destroyAllWindows()


if __name__ == "__main__":
    Simulation().run()
