import time
from loguru import logger
from webcam_mods.utils.cli_input import inp

memory = []  # memory consumption w*h*channels*1
replay_idx = -1
recording = False
replaying = False


def replay(frames, repeat=True):
    global replay_idx, replaying
    replay_idx += 1
    if replay_idx >= len(memory):
        if repeat:
            replay_idx = 0
        else:
            replaying = False
            replay_idx = -1
    return memory[replay_idx]


def replay_2(frames, repeat=True, fps=30):
    """ fps needs match the original fps to match playback speed without dropping frames """
    while True:
        for frame in frames:
            yield frame
            time.sleep(1 / fps)


def record(frame):
    global memory
    memory.append(frame)
    return frame


def reset_memory():
    global memory
    memory = []


# TODO support concurrent record and replay?
def process_input():
    global recording, replaying, memory
    if inp[0] == "record":
        inp[0] = ""
        logger.info("started recording")
        reset_memory()
        recording = True
    elif inp[0] == "stop":
        inp[0] = ""
        logger.info("stopping")
        recording = False
        replaying = False
    elif inp[0] == "replay":
        inp[0] = ""
        logger.info("start replaying")
        # also stops recording
        recording = False
        replaying = True


def engage(frame):
    process_input()
    if recording:
        return record(frame)
    elif replaying:
        return replay(memory)
    else:
        return frame
