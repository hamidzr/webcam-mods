import os
from pathlib import Path
import cv2

# Set the input video device config based on your hardware and driver capabilities.
# If you're using V4L2, you can use the v4l2-ctl utility to list the available
# devices and formats: `v4l2-ctl --list-formats-ext`
IN_WIDTH = int(os.getenv('IN_WIDTH', 640))
IN_HEIGHT = int(os.getenv('IN_HEIGHT', 480))
IN_FORMAT = os.getenv('IN_FORMAT', 'YUYV') # 'MJPG', 'YUYV', etc
IN_FPS = int(os.getenv('IN_FPS', 30))

VIDEO_OUT = '/dev/video10'
OUT_WIDTH = int(os.getenv('OUT_WIDTH', 640))
OUT_HEIGHT = int(os.getenv('OUT_HEIGHT', 480))
# adjust if perfromance is an issue in some of the process heavy mods
MAX_OUT_FPS = int(os.getenv('MAX_OUT_FPS', 30))

NO_SIGNAL_IMAGE = cv2.imread(f'{Path.cwd()}/data/nosignal.jpg')
DEFAULT_BG_IMAGE = f'{Path.cwd()}/data/bg.jpg'
ERROR_IMAGE = cv2.imread(f'{Path.cwd()}/data/errors/xp.jpg')
ON_DEMAND = os.getenv('ON_DEMAND') == 'True'

