1. clone https://github.com/hamidzr/webcam-mods
2. setup dependencies:
  1. virtual webcam device. `v4l2-ctl --list-devices`. README
    instructions here https://github.com/letmaik/pyvirtualcam#supported-virtual-cameras
  2. python
  3. input device
3. select webcam source, otherwise the first detected webcam would be used.
4. quick demo: crop-cam and interactive control
