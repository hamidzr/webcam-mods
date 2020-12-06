track-face:
	pipenv run python src/uses/track_face.py

crop-cam:
	pipenv run python src/uses/crop_cam.py

setup-webcam:
	modprobe v4l2loopback exclusive_caps=1 video_nr=10 card_label="v4l-cam"
