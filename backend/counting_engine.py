import cv2
import time
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from ultralytics import YOLO
from backend.database import record_product_counting_event, get_product_categories

class ProductCountingEngine:
    """
    AI Product & Fabric Counting Engine (Module B).
    - YOLOv8 object detection & ByteTrack persistent tracking.
    - Directional line & polygon zone counting.
    - Anti-double-count lock per tracked object ID.
    - Category totals (Taka bunches, finished sarees, yarn boxes, etc.).
    """
    def __init__(self, model_path: str = "yolov8n.pt"):
        print(f"[ProductEngine] Loading YOLO detection model: {model_path}...")
        self.model = YOLO(model_path)
        
        # Counting line: normalized (x1, y1) -> (x2, y2)
        self.line_x1: float = 0.10
        self.line_y1: float = 0.50
        self.line_x2: float = 0.90
        self.line_y2: float = 0.50

        # Optional Polygon Counting Zone: list of (x, y) normalized coordinates
        self.counting_polygon: Optional[List[Tuple[float, float]]] = None

        # Tracking state
        self.track_side: Dict[int, str] = {}
        self.counted_ids: Dict[int, float] = {} # {track_id: timestamp}
        self.recent_product_events: List[Dict[str, Any]] = []

        # Session totals
        self.session_counts: Dict[str, int] = {}

    def set_counting_line(self, x1: float, y1: float, x2: float, y2: float):
        self.line_x1 = max(0.0, min(1.0, x1))
        self.line_y1 = max(0.0, min(1.0, y1))
        self.line_x2 = max(0.0, min(1.0, x2))
        self.line_y2 = max(0.0, min(1.0, y2))

    def set_counting_polygon(self, polygon: List[Tuple[float, float]]):
        self.counting_polygon = polygon

    def _get_side_of_line(self, px: float, py: float) -> str:
        cross = (self.line_x2 - self.line_x1) * (py - self.line_y1) - (self.line_y2 - self.line_y1) * (px - self.line_x1)
        return "INSIDE" if cross >= 0 else "OUTSIDE"

    def process_frame(self, frame: np.ndarray, camera_id: str = "cam_01") -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """
        Runs YOLO detection & tracking on a video frame.
        Evaluates crossing events and draws bounding boxes + count tags.
        """
        h, w = frame.shape[:2]
        now = time.time()
        now_str = datetime.now().strftime("%H:%M:%S")
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Run tracking (classes: suitcase/box/sports ball/bottle or general objects)
        results = self.model.track(source=frame, persist=True, verbose=False, conf=0.35)
        
        detections = []
        if len(results) > 0 and results[0].boxes is not None and results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            track_ids = results[0].boxes.id.cpu().numpy().astype(int)
            clses = results[0].boxes.cls.cpu().numpy().astype(int)
            confs = results[0].boxes.conf.cpu().numpy()

            for i, box in enumerate(boxes):
                tid = int(track_ids[i])
                cid = int(clses[i])
                conf = float(confs[i])
                class_name = self.model.names.get(cid, f"item_{cid}")

                # Ground/center position
                norm_cx = ((box[0] + box[2]) / 2.0) / w
                norm_cy = ((box[1] + box[3]) / 2.0) / h

                cur_side = self._get_side_of_line(norm_cx, norm_cy)

                # Crossing detection
                if tid in self.track_side:
                    prev_side = self.track_side[tid]
                    if prev_side != cur_side:
                        # Check cooldown / duplicate prevention
                        if tid not in self.counted_ids or (now - self.counted_ids[tid] > 15.0):
                            self.counted_ids[tid] = now
                            direction = "IN" if (prev_side == "OUTSIDE" and cur_side == "INSIDE") else "OUT"
                            
                            # Increment count
                            self.session_counts[class_name] = self.session_counts.get(class_name, 0) + 1

                            # Record to database
                            record_product_counting_event(
                                camera_id=camera_id,
                                category=class_name,
                                direction=direction,
                                track_id=tid,
                                confidence=conf,
                                quantity=1,
                                shift_name="Day Shift",
                                tenant_id="default"
                            )

                            event_item = {
                                "time": now_str,
                                "category": class_name,
                                "direction": direction,
                                "track_id": tid,
                                "badge": f"{class_name.upper()} {direction}",
                                "msg": f"Product [{class_name}] crossed counting boundary {direction}."
                            }
                            self.recent_product_events.insert(0, event_item)
                            if len(self.recent_product_events) > 30:
                                self.recent_product_events = self.recent_product_events[:30]

                self.track_side[tid] = cur_side
                detections.append({
                    "track_id": tid,
                    "class_name": class_name,
                    "box": box.tolist(),
                    "conf": conf
                })

        return detections
