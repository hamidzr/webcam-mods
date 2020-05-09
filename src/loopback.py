import cv2
from contextlib import contextmanager

# We need to look at system information (os) and write to the device (fcntl)
import os
import fcntl
from mods.video_mods import crop

# WARN output dimentions should smaller than input

IN_WIDTH = 640
IN_HEIGHT = 480

OUT_WIDTH = 320  # 240
OUT_HEIGHT = 240  # 320


def readV4l2():
    # v4l2 was last updated in 2010
    with open(f'../v4l2/v4l2_fd_{OUT_WIDTH}x{OUT_HEIGHT}.buffer', 'rb') as f:
        format = f.read()
    return (-1060088315, format)


@contextmanager
def video_capture(w=640, h=480):
    # Grab the webcam feed and get the dimensions of a frame
    videoIn = cv2.VideoCapture(0)
    videoIn.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    videoIn.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    # Name and instantiate our loopback device
    devName = '/dev/video3'
    if not os.path.exists(devName):
        print("warning: device does not exist", devName)
    videoOut = open(devName, 'wb')

    req, format = readV4l2()
    fcntl.ioctl(videoOut, req, format)

    try:
        yield videoIn, videoOut
    finally:
        videoIn.release()
        videoOut.close()


def live_loop(mod):
    print("begin loopback write..")
    with video_capture(IN_WIDTH, IN_HEIGHT) as (cap, device):
        # This is the loop that reads from the webcam, edits, and then writes to the loopback
        while True:
            ret, frame = cap.read()
            # WARN: frame dimensions and format has to match readV4l2
            frame = mod(frame)
            # assert frame.shape[0] == OUT_HEIGHT
            # assert frame.shape[1] == OUT_WIDTH
            device.write(cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420))


if __name__ == "__main__":
    live_loop(lambda f: crop(f, OUT_WIDTH, OUT_HEIGHT, 0, 0))
