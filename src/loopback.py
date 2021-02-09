import cv2
import v4l2
from contextlib import contextmanager

# We need to look at system information (os) and write to the device (fcntl)
import os
import fcntl
from mods.video_mods import crop

# WARN output dimentions should smaller than input

IN_WIDTH = 640
IN_HEIGHT = 480

OUT_WIDTH = 240  # 240
OUT_HEIGHT = 240  # 320


def available_camera_indices(end: int = 3):
    """
    Check up to `end` video devices to find available ones.
    """
    index = 0
    arr = []
    i = end
    while i > 0:
        cap = cv2.VideoCapture(index)
        if cap.read()[0]:
            arr.append(index)
            cap.release()
        index += 1
        i -= 1
    return arr


VIDEO_IN = os.getenv('VIDEO_IN', available_camera_indices()[0])
VIDEO_OUT = 10

def prep_v4l2_descriptor(width, height, channels):
    # Set up the formatting of our loopback device
    format = v4l2.v4l2_format()
    format.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT
    format.fmt.pix.field = v4l2.V4L2_FIELD_NONE
    format.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_YUV420
    format.fmt.pix.width = width
    format.fmt.pix.height = height
    format.fmt.pix.bytesperline = width * channels
    format.fmt.pix.sizeimage = width * height * channels
    return (v4l2.VIDIOC_S_FMT, format)

@contextmanager
def video_capture(w=640, h=480):
    # Grab the webcam feed and get the dimensions of a frame
    videoIn = cv2.VideoCapture(VIDEO_IN)
    videoIn.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    videoIn.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    # Name and instantiate our loopback device
    devName = f'/dev/video{VIDEO_OUT}'
    if not os.path.exists(devName):
        print("warning: device does not exist", devName)
    with open(devName, 'wb') as videoOut:
        req, format = prep_v4l2_descriptor(OUT_WIDTH, OUT_HEIGHT, 3)
        try:
            fcntl.ioctl(videoOut, req, format)
            yield videoIn, videoOut
        finally:
            videoIn.release()


def live_loop(mod=None):
    print(f'begin loopback write from dev #{VIDEO_IN} to #{VIDEO_OUT}')
    with video_capture(IN_WIDTH, IN_HEIGHT) as (cap, device):
        # This is the loop that reads from the webcam, edits, and then writes to the loopback
        while True:
            ret, frame = cap.read()
            # WARN: frame dimensions and format has to match readV4l2
            if mod:
                frame = mod(frame)
            else:
                frame = crop(frame, OUT_WIDTH, OUT_HEIGHT, 0, 0)
            # assert frame.shape[0] == OUT_HEIGHT
            # assert frame.shape[1] == OUT_WIDTH
            device.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420))


if __name__ == "__main__":
    live_loop()
