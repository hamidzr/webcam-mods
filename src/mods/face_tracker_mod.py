from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from ultra_light import find_faces, draw_overlays
from mods.video_mods import crop
import math
import numpy as np


cur_box = (0, 0, 200, 200)
frame_count = 0


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


def track_face(frame, draw_overlays=False, prediction_rate=30, move_threshold=50):
    global cur_box, frame_count
    rate = prediction_rate  # predict once every n frame
    skip_prediction = frame_count % rate != 0
    frame_count += 1

    if not skip_prediction:
        boxes, probs = find_faces(frame)
        if len(boxes) > 0:  # if found at least one face
            box = boxes[0, :]
            if face_has_moved(box, move_threshold):
                cur_box = box

    if draw_overlays:
        draw_overlays(frame, np.asarray([cur_box]))

    return align_box(frame)
