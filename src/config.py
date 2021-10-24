import os
from pathlib import Path
import cv2

IN_WIDTH = int(os.getenv('IN_WIDTH', 640))
IN_HEIGHT = int(os.getenv('IN_HEIGHT', 480))
NO_SIGNAL_IMG = f'{Path.cwd()}/data/nosignal.jpg'

VIDEO_OUT = 10
OUT_WIDTH = 320  # 240
OUT_HEIGHT = 240  # 320
# OUT_WIDTH = 640
# OUT_HEIGHT = 480
MAX_OUT_FPS = int(os.getenv('MAX_OUT_FPS', 30))

no_signal_img = cv2.imread(NO_SIGNAL_IMG)
