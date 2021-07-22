from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.video_mods import crop, pad_inward_centered
from pynput.keyboard import Key, Listener
from mods.record_replay import engage
import os.path

cur_keys = set()
# TODO central config save and load support
CONF_FILE = '.webcam.conf'
shmem = [0, 0, 0, 0] # pos, pos, horizontal_pad, vertical_pad
if os.path.isfile(CONF_FILE):
    with open(CONF_FILE, 'r') as f:
        line = f.readline()
        if line != '':
            shmem = [int(x) for x in line.split(',')]
print("cam position config", shmem)

JUMP = 10  # pixels



def on_press(key):
    global shmem, cur_keys
    cur_keys.add(key)
    target_keys = [Key.ctrl, Key.alt]
    if not any(key in cur_keys for key in target_keys):
        return
    if (Key.ctrl in cur_keys):
        if key == Key.right:
            shmem[0] -= JUMP
        elif key == Key.left:
            shmem[0] += JUMP
        elif key == Key.up:
            shmem[1] -= JUMP
        elif key == Key.down:
            shmem[1] += JUMP
    if (Key.alt in cur_keys):
        if key == Key.right:
            shmem[2] -= JUMP
        elif key == Key.left:
            shmem[2] += JUMP
        elif key == Key.up:
            shmem[3] -= JUMP
        elif key == Key.down:
            shmem[3] += JUMP
    # TODO reduce unnecessary writes
    val_max = max(OUT_WIDTH, OUT_HEIGHT)
    shmem = [min(max(x,0), val_max) for x in shmem] # limit the values albeit poorly
    with open(CONF_FILE, 'w+') as f:
        f.write(','.join([str(x) for x in shmem]))


def on_release(key):
    if key in cur_keys:
        cur_keys.remove(key)


key_listener = Listener(on_press=on_press, on_release=on_release)
key_listener.start()


def frame_modr(frame):
    frame = crop(frame, OUT_WIDTH, OUT_HEIGHT, shmem[0], shmem[1])
    frame = pad_inward_centered(frame, horizontal=shmem[2], vertical=shmem[3], color=0)
    return engage(frame)


if __name__ == '__main__':
    live_loop(frame_modr)
