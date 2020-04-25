# Going to need these
import cv2
import numpy as np

# We need to look at system information (os) and write to the device (fcntl)
import os
import fcntl


# Do whatever you want to the capture here
def frame_modr(frame):
    kernel = np.ones((5, 3)).astype(np.uint8)
    grad = cv2.morphologyEx(frame.copy(), cv2.MORPH_GRADIENT, kernel)
    mapped_grad = cv2.applyColorMap(grad, cv2.COLORMAP_JET)
    return mapped_grad

def crop(frame, w: int, h: int, x=0, y=0):
    return frame[y:y+h, x:x+w].copy()

# v4l2 was last updated in 2010
def readV4l2():
    with open('../v4l2/format.buffer', 'rb') as f:
        format = f.read()
    return (-1060088315, format)


def run():
    # Grab the webcam feed and get the dimensions of a frame
    cap                   = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    ret,im                = cap.read()
    height,width,channels = im.shape

    # Name and instantiate our loopback device
    devName = '/dev/video3'
    if not os.path.exists(devName):
        print ("Warning: device does not exist", devName)
    device = open(devName, 'wb')

    req, format = readV4l2()
    fcntl.ioctl(device, req, format)
    print("begin loopback write")

    # This is the loop that reads from the webcam, edits, and then writes to the loopback
    while True:
        ret,im       = cap.read()
        # modded_frame = frame_modr(im)
        modded_frame = crop(im, 300, 300, 0, 0)
        device.write(modded_frame)


if __name__ == "__main__":
    run()
