import os
from pathlib import Path
import cv2

IN_WIDTH = int(os.getenv('IN_WIDTH', 640))
IN_HEIGHT = int(os.getenv('IN_HEIGHT', 480))

VIDEO_OUT = 10
OUT_WIDTH = int(os.getenv('OUT_WIDTH', 640))
OUT_HEIGHT = int(os.getenv('OUT_HEIGHT', 480))

# adjust if perfromance is an issue in some of the process heavy mods
MAX_OUT_FPS = int(os.getenv('MAX_OUT_FPS', 30))

NO_SIGNAL_IMAGE = cv2.imread(f'{Path.cwd()}/data/nosignal.jpg')
DEFAULT_BG_IMAGE = f'{Path.cwd()}/data/bg.jpg'
ERROR_IMAGE = cv2.imread(f'{Path.cwd()}/data/errors/xp.jpg')
ON_DEMAND = os.getenv('ON_DEMAND') == 'True'

