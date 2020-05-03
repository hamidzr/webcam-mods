import cv2
import dlib
import numpy as np
from imutils import face_utils
from box_utils import *

import onnx
import onnxruntime as ort
from onnx_tf.backend import prepare
from time import sleep

onnx_path = './ultra_light_640.onnx'
onnx_model = onnx.load(onnx_path)
predictor = prepare(onnx_model)
ort_session = ort.InferenceSession(onnx_path)
input_name = ort_session.get_inputs()[0].name


def prepare_frame(frame):
    # preprocess img acquired
    img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)  # convert bgr to rgb
    # img = cv2.resize(img, (640, 480)) # resize
    img_mean = np.array([127, 127, 127])
    img = (img - img_mean) / 128
    img = np.transpose(img, [2, 0, 1])
    img = np.expand_dims(img, axis=0)
    img = img.astype(np.float32)
    return img


def draw_overlays(frame, boxes, probs=None):
    for i in range(boxes.shape[0]):
        box = boxes[i, :]
        x1, y1, x2, y2 = box
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (80, 18, 236), 2)
        cv2.rectangle(frame, (x1, y2 - 20), (x2, y2),
                      (80, 18, 236), cv2.FILLED)
        font = cv2.FONT_HERSHEY_DUPLEX
        if probs:
            text = f"Face: {round(probs[i], 2)}"
        else:
            text = f"Face"
        cv2.putText(frame, text, (x1 + 6, y2 - 6),
                    font, 0.3, (255, 255, 255), 1)


def find_faces(frame):
    h, w, _ = frame.shape

    img = prepare_frame(frame)

    confidences, boxes = ort_session.run(None, {input_name: img})
    boxes, labels, probs = predict(w, h, confidences, boxes, 0.7)

    return (boxes, probs)


def interactive_webcam():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    while True:
        # sleep(0.3)
        ret, frame = cap.read()
        if frame is not None:
            boxes, probs = find_faces(frame)
            draw_overlays(frame, boxes, probs)
        # Hit 'q' on the keyboard to quit!
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # cv2.imshow('Video', frame)
    # release handle to the webcam
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    interactive_webcam()
