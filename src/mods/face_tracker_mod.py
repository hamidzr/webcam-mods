from src.ultra_light import find_faces, draw_overlays
from src.loopback import OUT_WIDTH, OUT_HEIGHT
from src.mods.video_mods import crop
import math
import numpy as np
import time
import threading


cur_box = (0, 0, 200, 200)
shmem = [None]


def face_has_moved(new_box, move_threshold: int):
    x1, y1, x2, y2 = new_box
    # only consider the top left corner of the box
    # OPT or do a simpler faster check
    dist = math.sqrt((x1 - cur_box[0])**2 + (y1 - cur_box[1])**2)
    return dist > move_threshold


def align_box(frame):
    # calculate the crop based to center the face box
    x1, y1, x2, y2 = cur_box
    bw = x2-x1  # box width
    bh = y2-y1
    pad_x = (OUT_WIDTH - bw) // 2
    pad_y = (OUT_HEIGHT - bh) // 2
    return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-pad_x, y1-pad_y)
    # align the easy way: pad the face rectangels the easy way
    # return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-50, y1-50)


def init(prediction_rate=1, move_threshold=50):
    # set up the prediction thread
    def make_prediction():
        global cur_box
        while True:
            if shmem[0] is None:
                time.sleep(0.01)
                continue
            boxes, probs = find_faces(shmem[0])
            if len(boxes) > 0:  # if found at least one face
                box = boxes[0, :]
                if face_has_moved(box, move_threshold):
                    cur_box = box
            time.sleep(1/prediction_rate)

    pred_thread = threading.Thread(
        target=make_prediction, daemon=True)
    pred_thread.start()
    return pred_thread


def track_face(frame, overlay=False):
    global shmem
    shmem[0] = frame

    if overlay:
        draw_overlays(frame, np.asarray([cur_box]))

    return align_box(frame)
