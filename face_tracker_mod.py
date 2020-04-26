from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from ultra_light import find_faces
from video_mods import crop

last_pos = (0, 0)
frame_count = 0


def track_face(frame):
    global last_pos, frame_count
    rate = 30  # predict once every n frame
    found_face = False
    skip_prediction = frame_count % rate != 0
    frame_count += 1

    if not skip_prediction:
        boxes, probs = find_faces(frame)
        found_face = len(boxes) > 0

    # pad the dumb way
    pad = 50

    if not found_face or skip_prediction:
        return crop(frame, OUT_WIDTH, OUT_HEIGHT, last_pos[0]-pad, last_pos[1]-pad)

    box = boxes[0, :]
    x1, y1, x2, y2 = box
    last_pos = (x1, y1)
    return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-pad, y1-pad)


if __name__ == "__main__":
    live_loop(track_face)
