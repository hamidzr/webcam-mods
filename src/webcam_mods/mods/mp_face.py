from webcam_mods.geometry import Rect
import cv2
from mediapipe.python.solutions import face_detection
from typing import Optional, Tuple
from webcam_mods.utils.video import sleep_until_fps


fd: Optional[face_detection.FaceDetection] = None
# fd.close()
def init() -> face_detection.FaceDetection:
    global fd
    if fd is None:
      fd = face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.6)
    return fd

def predict(frame) -> Optional[Tuple[int, int, int, int]]:
    """
    predicts a bounding box around the first face found:
    xmin: 0.43449878692626953
    ymin: 0.47915118932724
    width: 0.1905471682548523
    height: 0.2540317177772522
    """
    image = frame
    fh, fw, _ = frame.shape
    fd = init()
      # Convert the BGR image to RGB and process it with MediaPipe Face Detection.
    results = fd.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if not results.detections:
      return None
    detection = results.detections[0] # target detection supporting single face usage.
    # print('Nose tip:')
    # print(face_detection.get_key_point(
    #     detection, face_detection.FaceKeyPoint.NOSE_TIP))
    return detection.location_data.relative_bounding_box

def abs_boundingbox(frame, relbb) -> Rect:
    fh, fw, _ = frame.shape
    return Rect(w=int(relbb.width*fw), h=int(relbb.height*fh),
         l=int(relbb.xmin*fw), t=int(relbb.ymin*fh))

if __name__ == '__main__':
    from webcam_mods.input.video_dev import Webcam
    init()
    with Webcam() as (cam, _):
        while True:
            frame = cam.frame()
            pred = predict(frame)
            # print(abs_boundingbox(frame, pred))
            sleep_until_fps(5)

# from webcam_mods.loopback import OUT_WIDTH, OUT_HEIGHT
# from webcam_mods.mods.video_mods import crop
# import math
# import numpy as np
# import time
# import threading


# cur_box = (0, 0, 200, 200)
# shmem = [None]


# def face_has_moved(new_box, move_threshold: int):
#     x1, y1, x2, y2 = new_box
#     # only consider the top left corner of the box
#     # OPT or do a simpler faster check
#     dist = math.sqrt((x1 - cur_box[0])**2 + (y1 - cur_box[1])**2)
#     return dist > move_threshold


# def align_box(frame):
#     # calculate the crop based to center the face box
#     x1, y1, x2, y2 = cur_box
#     bw = x2-x1  # box width
#     bh = y2-y1
#     pad_x = (OUT_WIDTH - bw) // 2
#     pad_y = (OUT_HEIGHT - bh) // 2
#     return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-pad_x, y1-pad_y)
#     # align the easy way: pad the face rectangels the easy way
#     # return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-50, y1-50)


# def init(prediction_rate=1, move_threshold=50):
#     # set up the prediction thread
#     def make_prediction():
#         global cur_box
#         while True:
#             if shmem[0] is None:
#                 time.sleep(0.01)
#                 continue
#             boxes, probs = find_faces(shmem[0])
#             if len(boxes) > 0:  # if found at least one face
#                 box = boxes[0, :]
#                 if face_has_moved(box, move_threshold):
#                     cur_box = box
#             time.sleep(1/prediction_rate)

#     pred_thread = threading.Thread(
#         target=make_prediction, daemon=True)
#     pred_thread.start()
#     return pred_thread
