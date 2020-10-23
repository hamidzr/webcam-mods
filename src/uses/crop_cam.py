from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.video_mods import crop
from pynput.keyboard import Key, Listener
from mods.record_replay import engage

cur_keys = set()
# TODO central config save and load support
shmem = [0, 0]
with open('.webcam.conf', 'r') as f:
    line = f.readline()
    if line != '':
        shmem = [int(x) for x in line.split(',')]
print("cam positioned at", shmem)

JUMP = 10  # pixels


def on_press(key):
    global shmem, cur_keys
    cur_keys.add(key)
    if (Key.ctrl not in cur_keys):
        return

    if key == Key.right:
        shmem[0] += JUMP
    elif key == Key.left:
        shmem[0] -= JUMP
    elif key == Key.up:
        shmem[1] -= JUMP
    elif key == Key.down:
        shmem[1] += JUMP
    with open('.webcam.conf', 'w+') as f:
        f.write(','.join([str(x) for x in shmem]))


def on_release(key):
    if key in cur_keys:
        cur_keys.remove(key)


key_listener = Listener(on_press=on_press, on_release=on_release)
key_listener.start()


def frame_modr(frame):
    frame = crop(frame, OUT_WIDTH, OUT_HEIGHT, shmem[0], shmem[1])
    return engage(frame)


live_loop(frame_modr)
