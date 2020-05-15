from loopback import live_loop, OUT_WIDTH, OUT_HEIGHT
from mods.video_mods import crop
from pynput.keyboard import Key, Listener

cur_keys = set()
shmem = [0, 0]

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


def on_release(key):
    if key in cur_keys:
        cur_keys.remove(key)


key_listener = Listener(on_press=on_press, on_release=on_release)
key_listener.start()

live_loop(lambda f: crop(f, OUT_WIDTH, OUT_HEIGHT, shmem[0], shmem[1]))
