from loopback import live_loop
from mods.face_tracker_mod import track_face

if __name__ == "__main__":
    live_loop(track_face)
