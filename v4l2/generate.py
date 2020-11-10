import v4l2

# Deprecated. This can be used if there the v4l2 package doesn't play nicely with Python3.


def setup_fromat(width, height, channels):
    # Set up the formatting of our loopback device
    format = v4l2.v4l2_format()
    format.type = v4l2.V4L2_BUF_TYPE_VIDEO_OUTPUT
    format.fmt.pix.field = v4l2.V4L2_FIELD_NONE
    format.fmt.pix.pixelformat = v4l2.V4L2_PIX_FMT_YUV420
    format.fmt.pix.width = width
    format.fmt.pix.height = height
    format.fmt.pix.bytesperline = width * channels
    format.fmt.pix.sizeimage = width * height * channels
    return format


def genV4l2(width, height, channels):
    format = setup_fromat(width, height, channels)

    # print(dir(v4l2))

    f = open('v4l2_fd_{}x{}.buffer'.format(width, height), 'wb')
    f.write(format)
    f.close()
    print((v4l2.VIDIOC_S_FMT, '*.buffer'))


if __name__ == "__main__":
    genV4l2(300, 300, 3)
    genV4l2(350, 350, 3)
    genV4l2(640, 480, 3)
    genV4l2(240, 320, 3)
    genV4l2(320, 240, 3)
