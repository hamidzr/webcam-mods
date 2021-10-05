import cv2
from mediapipe.python.solutions import face_detection
from typing import Optional, Tuple


fd: Optional[face_detection.FaceDetection] = None
# fd.close()
def init() -> face_detection.FaceDetection:
  global fd
  if fd is None:
    fd = face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.6)
  return fd

def predict(frame) -> Optional[Tuple[int, int, int, int]]:
  """
  predicts a bounding box around the first face found:
  xmin: 0.43449878692626953
  ymin: 0.47915118932724
  width: 0.1905471682548523
  height: 0.2540317177772522
  """
  image = frame
  fh, fw, _ = frame.shape
  fd = init()
    # Convert the BGR image to RGB and process it with MediaPipe Face Detection.
  results = fd.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
  if not results.detections:
    return None
  detection = results.detections[0] # target detection supporting single face usage.
  # print('Nose tip:')
  # print(face_detection.get_key_point(
  #     detection, face_detection.FaceKeyPoint.NOSE_TIP))
  return detection.location_data.relative_bounding_box
