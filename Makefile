face-cam:
	pipenv run python face_tracker_mod.py

setup-webcam:
	modprobe v4l2loopback exclusive_caps=1 video_nr=3 card_label="v4l-cam"
