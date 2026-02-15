"""Camera capture and pose detection for posture service."""

import gc
import os
import threading
import time
import urllib.request
from typing import Optional, List, Callable

from gi.repository import GLib

# Lower resolution for reduced memory footprint (was 640x480)
_FRAME_WIDTH = 320
_FRAME_HEIGHT = 240


class CameraProcessor:
    """Handles camera capture and pose detection using MediaPipe Tasks API.

    Heavy libraries (cv2, mediapipe, numpy) are imported lazily inside
    _process_loop() so that merely importing this module costs almost nothing.
    This prevents OOM in environments where the posture service is registered
    but never started (e.g. no camera present).
    """

    POSE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"

    def __init__(self, model_dir: Optional[str] = None):
        self.cap = None
        self.pose_landmarker = None
        self.face_detector = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.on_pose_detected: Optional[Callable[[float], None]] = None
        self.on_no_detection: Optional[Callable[[], None]] = None
        self.on_camera_error: Optional[Callable[[str], None]] = None

        self.frame_interval = 0.2  # 5 fps (was 10 fps)
        self.last_frame_time = 0
        self.camera_index = 0

        self.model_dir = model_dir or os.path.expanduser("~/.local/share/praya/models")
        os.makedirs(self.model_dir, exist_ok=True)

        # Lazy-loaded references (set in _process_loop)
        self._cv2 = None
        self._mp = None
        self._mp_tasks = None
        self._vision = None
        self._rgb_buffer = None

        # Consecutive pose failures before loading face detector as fallback
        self._pose_fail_count = 0
        self._POSE_FAIL_THRESHOLD = 30  # ~6 seconds at 5 fps

    def _download_model(self, url: str, filename: str) -> str:
        """Download model if not exists."""
        filepath = os.path.join(self.model_dir, filename)
        if not os.path.exists(filepath):
            print(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, filepath)
            print(f"Downloaded {filename}")
        return filepath

    def _check_camera(self, index: int) -> bool:
        """Check if a camera is available without keeping it open."""
        import cv2
        cap = cv2.VideoCapture(index)
        available = cap.isOpened()
        cap.release()
        return available

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
            self.thread.join(timeout=2.0)
            self.thread = None
        if self.cap:
            self.cap.release()
            self.cap = None
        if self.pose_landmarker:
            self.pose_landmarker.close()
            self.pose_landmarker = None
        if self.face_detector:
            self.face_detector.close()
            self.face_detector = None
        self._rgb_buffer = None
        self._cv2 = None
        self._mp = None
        self._mp_tasks = None
        self._vision = None
        gc.collect()

    def _load_libs(self):
        """Import heavy libraries on demand."""
        import cv2
        import numpy as np
        import mediapipe as mp
        from mediapipe.tasks import python as mp_tasks
        from mediapipe.tasks.python import vision

        self._cv2 = cv2
        self._mp = mp
        self._mp_tasks = mp_tasks
        self._vision = vision
        self._rgb_buffer = np.empty((_FRAME_HEIGHT, _FRAME_WIDTH, 3), dtype=np.uint8)

    def _init_face_detector(self) -> bool:
        """Lazy-load face detector only when pose detection fails repeatedly."""
        if self.face_detector is not None:
            return True
        try:
            face_model_path = self._download_model(self.FACE_MODEL_URL, "blaze_face_short_range.tflite")
            face_options = self._vision.FaceDetectorOptions(
                base_options=self._mp_tasks.BaseOptions(model_asset_path=face_model_path),
                running_mode=self._vision.RunningMode.IMAGE,
                min_detection_confidence=0.5
            )
            self.face_detector = self._vision.FaceDetector.create_from_options(face_options)
            print("[camera] Face detector loaded as fallback")
            return True
        except Exception as e:
            print(f"[camera] Failed to load face detector: {e}")
            return False

    def _process_loop(self):
        """Main processing loop."""
        # Import heavy libraries only when actually starting camera processing
        try:
            self._load_libs()
        except ImportError as e:
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, f"Missing dependency: {e}")
            return

        cv2 = self._cv2
        mp = self._mp
        vision = self._vision

        try:
            pose_model_path = self._download_model(self.POSE_MODEL_URL, "pose_landmarker_lite.task")
        except Exception as e:
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, f"Failed to download models: {e}")
            return

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, "Failed to open camera")
            return

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, _FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _FRAME_HEIGHT)
        # Minimize internal camera buffer to reduce memory
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        try:
            pose_options = vision.PoseLandmarkerOptions(
                base_options=self._mp_tasks.BaseOptions(model_asset_path=pose_model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.pose_landmarker = vision.PoseLandmarker.create_from_options(pose_options)
        except Exception as e:
            if self.on_camera_error:
                GLib.idle_add(self.on_camera_error, f"Failed to initialize MediaPipe: {e}")
            return

        # Free model file memory after loading into inference engine
        gc.collect()

        while self.running:
            current_time = time.time()
            elapsed = current_time - self.last_frame_time
            if elapsed < self.frame_interval:
                time.sleep(self.frame_interval - elapsed)
                continue
            self.last_frame_time = time.time()

            ret, frame = self.cap.read()
            if not ret:
                continue

            # Convert BGR->RGB in-place into pre-allocated buffer
            cv2.cvtColor(frame, cv2.COLOR_BGR2RGB, dst=self._rgb_buffer)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=self._rgb_buffer)

            detected = False
            try:
                pose_results = self.pose_landmarker.detect(mp_image)
                if pose_results.pose_landmarks and len(pose_results.pose_landmarks) > 0:
                    landmarks = pose_results.pose_landmarks[0]
                    if len(landmarks) > 0:
                        nose = landmarks[0]
                        if self.on_pose_detected:
                            GLib.idle_add(self.on_pose_detected, nose.y)
                        self._pose_fail_count = 0
                        detected = True
            except Exception:
                pass

            if not detected:
                self._pose_fail_count += 1

                # Only load face detector after sustained pose failure
                if self._pose_fail_count >= self._POSE_FAIL_THRESHOLD:
                    if self._init_face_detector():
                        try:
                            face_results = self.face_detector.detect(mp_image)
                            if face_results.detections and len(face_results.detections) > 0:
                                detection = face_results.detections[0]
                                bbox = detection.bounding_box
                                face_y = (bbox.origin_y + bbox.height / 2) / _FRAME_HEIGHT
                                if self.on_pose_detected:
                                    GLib.idle_add(self.on_pose_detected, face_y)
                                detected = True
                        except Exception:
                            pass

            if not detected:
                if self.on_no_detection:
                    GLib.idle_add(self.on_no_detection)

            # Release frame reference promptly
            del frame, mp_image

        # Cleanup
        if self.pose_landmarker:
            self.pose_landmarker.close()
            self.pose_landmarker = None
        if self.face_detector:
            self.face_detector.close()
            self.face_detector = None
        if self.cap:
            self.cap.release()
            self.cap = None
