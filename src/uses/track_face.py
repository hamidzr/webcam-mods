from loopback import live_loop
import mods.face_tracker_mod as ft

ft.init(prediction_rate=0.5)
live_loop(ft.track_face)
