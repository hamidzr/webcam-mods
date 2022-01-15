import os
from pathlib import Path

# Set the input video device config based on your hardware and driver capabilities.
# If you're using V4L2, you can use the v4l2-ctl utility to list the available
# devices and formats: `v4l2-ctl --list-formats-ext`
IN_WIDTH = int(os.getenv('IN_WIDTH', 640))
IN_HEIGHT = int(os.getenv('IN_HEIGHT', 480))
IN_FORMAT = os.getenv('IN_FORMAT', 'YUYV') # 'MJPG', 'YUYV', etc
IN_FPS = int(os.getenv('IN_FPS', 30))

VIDEO_IN = int(os.getenv('VIDEO_IN', 0)) # CHECK do we need to support other path structures than /dev/videoINDEX
VIDEO_OUT = os.getenv('VIDEO_OUT', '/dev/video10') # TODO to int

OUT_WIDTH = int(os.getenv('OUT_WIDTH', 640))
OUT_HEIGHT = int(os.getenv('OUT_HEIGHT', 480))
# adjust if perfromance is an issue in some of the process heavy mods
MAX_OUT_FPS = int(os.getenv('MAX_OUT_FPS', 30))

data_root = Path(__file__).parent / 'data'
NO_SIGNAL_IMAGE = data_root / 'nosignal.jpg'
DEFAULT_BG_IMAGE = data_root / 'bg.jpg'
ERROR_IMAGE = data_root / 'errors' / 'xp.jpg'

ON_DEMAND = os.getenv('ON_DEMAND') == 'True'
