import fcntl
import os
from contextlib import contextmanager

def prep_v4l2_descriptor(width, height, channels):
    try:
        import v4l2
    except:
        print('v4l2 package is not available')
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
def video_output(out_w=320, out_h=240, output_dev=10):
    # Name and instantiate our loopback device
    if not os.path.exists(output_dev):
        print("warning: device does not exist", output_dev)
    with open(output_dev, 'wb') as videoOut:
        req, format = prep_v4l2_descriptor(out_w, out_h, 3)
        fcntl.ioctl(videoOut, req, format)
        yield videoOut
