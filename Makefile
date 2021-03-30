default: setup-webcam

track-face:
	pipenv run python src/uses/track_face.py

crop-cam:
	pipenv run python src/uses/crop_cam.py

add-video-dev:
	# sudo fuser /dev/video10 # to find out what is using the device
	pkill gst-launch &> /dev/null || true
	rmmod v4l2loopback &> /dev/null || true
	modprobe v4l2loopback video_nr=10 card_label="v4l-cam";

setup-webcam: add-video-dev
	v4l2loopback-ctl set-caps 'video/x-raw,format=I420,width=320,height=240' /dev/video10
