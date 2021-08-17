from src.loopback import live_loop
import src.mods.face_tracker_mod as ft
from src.mods.record_replay import engage

ft.init(prediction_rate=0.5)


def frame_modr(frame):
    frame = ft.track_face(frame)
    return engage(frame)


live_loop(frame_modr)
