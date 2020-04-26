from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from ultra_light import find_faces
from video_mods import crop
import math


# pad the face rectangels the easy way
PAD = 50

last_pos = (0, 0)
frame_count = 0


def face_has_moved(new_x, new_y):
    MOVE_THRESHOLD = 20.0  # pixel
    # OPT or do a simpler faster check
    dist = math.sqrt((new_x - last_pos[0])**2 + (new_y - last_pos[1])**2)
    return dist > MOVE_THRESHOLD


def crop_as_before(frame):
    return crop(frame, OUT_WIDTH, OUT_HEIGHT, last_pos[0]-PAD, last_pos[1]-PAD)


def track_face(frame):
    global last_pos, frame_count
    rate = 30  # predict once every n frame
    found_face = False
    skip_prediction = frame_count % rate != 0
    frame_count += 1

    if not skip_prediction:
        boxes, probs = find_faces(frame)
        found_face = len(boxes) > 0

    if not found_face or skip_prediction:
        return crop_as_before(frame)

    box = boxes[0, :]
    x1, y1, x2, y2 = box
    if face_has_moved(x1, y1):
        last_pos = (x1, y1)
        return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-PAD, y1-PAD)
    else:
        return crop_as_before(frame)


if __name__ == "__main__":
    live_loop(track_face)
