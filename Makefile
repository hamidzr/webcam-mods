default: add-video-dev

track-face:
	pipenv run python src/uses/track_face.py

bg-remove:
	pipenv run python src/uses/bg_removal.py

bg-swap:
	# TODO fix background resizing
	# using bg-remove for now
	$(MAKE) bg-remove

crop-cam:
	pipenv run python src/uses/crop_cam.py

# create a virtual video device on Linux
add-video-dev:
	# sudo fuser /dev/video10 # to find out what is using the device
	pkill gst-launch &> /dev/null || true
	rmmod v4l2loopback &> /dev/null || true
	modprobe v4l2loopback devices=1 max_buffers=2 exclusive_caps=1 video_nr=10 card_label="v4l-cam"

# setup-webcam: add-video-dev
# 	v4l2loopback-ctl set-caps 'video/x-raw,format=I420,width=320,height=240' /dev/video10
