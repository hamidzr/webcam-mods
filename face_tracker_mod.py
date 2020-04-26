from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from ultra_light import find_faces
from video_mods import crop


def track_face(frame):
    boxes, probs = find_faces(frame)
    have_face = len(boxes) > 0

    if not have_face:
        return crop(frame, OUT_WIDTH, OUT_HEIGHT, 0, 0)

    box = boxes[0, :]
    x1, y1, x2, y2 = box
    # pad the dumb way
    pad = 50
    return crop(frame, OUT_WIDTH, OUT_HEIGHT, x1-pad, y1-pad)


if __name__ == "__main__":
    live_loop(track_face)
