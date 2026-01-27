"""Camera capture and pose detection for posture service."""

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision
import threading
import urllib.request
import os
import time
from typing import Optional, List, Callable

from gi.repository import GLib


class CameraProcessor:
    """Handles camera capture and pose detection using MediaPipe Tasks API."""

    POSE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"

    def __init__(self, model_dir: Optional[str] = None):
        self.cap: Optional[cv2.VideoCapture] = None
        self.pose_landmarker = None
        self.face_detector = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.on_pose_detected: Optional[Callable[[float], None]] = None
        self.on_no_detection: Optional[Callable[[], None]] = None
        self.on_camera_error: Optional[Callable[[str], None]] = None

        self.frame_interval = 0.1  # 10fps
        self.last_frame_time = 0
        self.camera_index = 0

        self.model_dir = model_dir or os.path.expanduser("~/.local/share/praya/models")
        os.makedirs(self.model_dir, exist_ok=True)

    def _download_model(self, url: str, filename: str) -> str:
        """Download model if not exists."""
        filepath = os.path.join(self.model_dir, filename)
        if not os.path.exists(filepath):
            print(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, filepath)
            print(f"Downloaded {filename}")
        return filepath

    def get_available_cameras(self) -> List[tuple]:
        """Get list of available cameras."""
        cameras = []
        for i in range(10):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                name = f"Camera {i}"
                cameras.append((i, name))
                cap.release()
        return cameras

    def start(self, camera_index: int = 0):
        """Start camera capture and processing."""
        self.camera_index = camera_index
        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop camera capture."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.cap:
            self.cap.release()
            self.cap = None

    def _process_loop(self):
        """Main processing loop."""
        try:
            pose_model_path = self._download_model(self.POSE_MODEL_URL, "pose_landmarker_lite.task")
            face_model_path = self._download_model(self.FACE_MODEL_URL, "blaze_face_short_range.tflite")
        except Exception as e:
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, f"Failed to download models: {e}")
            return

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, "Failed to open camera")
            return

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        try:
            pose_options = vision.PoseLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=pose_model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)

            face_options = vision.FaceDetectorOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=face_model_path),
                running_mode=vision.RunningMode.IMAGE,
                min_detection_confidence=0.5
            )
            self.face_detector = vision.FaceDetector.create_from_options(face_options)
        except Exception as e:
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, f"Failed to initialize MediaPipe: {e}")
            return

        while self.running:
            current_time = time.time()
            if current_time - self.last_frame_time < self.frame_interval:
                time.sleep(0.01)
                continue
            self.last_frame_time = current_time

            ret, frame = self.cap.read()
            if not ret:
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            try:
                pose_results = self.pose_landmarker.detect(mp_image)
                if pose_results.pose_landmarks and len(pose_results.pose_landmarks) > 0:
                    landmarks = pose_results.pose_landmarks[0]
                    if len(landmarks) > 0:
                        nose = landmarks[0]
                        if self.on_pose_detected:
                            GLib.idle_add(self.on_pose_detected, nose.y)
                        continue
            except Exception:
                pass

            try:
                face_results = self.face_detector.detect(mp_image)
                if face_results.detections and len(face_results.detections) > 0:
                    detection = face_results.detections[0]
                    bbox = detection.bounding_box
                    frame_height = rgb_frame.shape[0]
                    face_y = (bbox.origin_y + bbox.height / 2) / frame_height
                    if self.on_pose_detected:
                        GLib.idle_add(self.on_pose_detected, face_y)
                    continue
            except Exception:
                pass

            if self.on_no_detection:
                GLib.idle_add(self.on_no_detection)

        if self.pose_landmarker:
            self.pose_landmarker.close()
        if self.face_detector:
            self.face_detector.close()
        self.cap.release()
