track-face:
	pipenv run python src/uses/track_face.py

crop-cam:
	pipenv run python src/uses/crop_cam.py

setup-webcam:
	# pkill -f v4l2loopback-ctl;
	rmmod v4l2loopback
	modprobe v4l2loopback video_nr=10 card_label="v4l-cam";
	v4l2loopback-ctl set-caps 'video/x-raw,format=I420,width=320,height=240' /dev/video10
