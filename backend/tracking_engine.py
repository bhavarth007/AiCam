import time
import cv2
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from backend.config import LOCK_DOUBLE_COUNT_COOLDOWN, LINE_CROSSING_BUFFER
from backend.database import record_gate_event, log_unknown_visitor

class GateTrackingEngine:
    def __init__(self, line_orientation: str = "horizontal", line_pos_ratio: float = 0.55, face_engine=None):
        """
        line_orientation: 'horizontal' (Top=Outside, Bottom=Inside) or 'vertical' (Left=Outside, Right=Inside)
        line_pos_ratio: position of the gate line as fraction of dimension (0.0 to 1.0)
        """
        self.line_orientation = line_orientation
        self.line_pos_ratio = line_pos_ratio
        self.face_engine = face_engine
        
        # Track history: {track_id: [(cx, cy, timestamp), ...]}
        self.track_history: Dict[int, List[Tuple[float, float, float]]] = {}
        
        # Track status: {track_id: 'OUTSIDE' | 'INSIDE'}
        self.track_side: Dict[int, str] = {}
        
        # Anti-double count cooldown: {key: timestamp}
        self.cooldown_locks: Dict[str, float] = {}
        
        # Session Counters
        self.count_in = 0
        self.count_out = 0
        self.count_unknown = 0
        
        # Recent live event feed for UI
        self.recent_events: List[Dict[str, Any]] = []

    def set_line_position(self, ratio: float, orientation: Optional[str] = None):
        self.line_pos_ratio = max(0.1, min(0.9, ratio))
        if orientation in ["horizontal", "vertical"]:
            self.line_orientation = orientation

    def is_locked(self, lock_key: str) -> bool:
        now = time.time()
        if lock_key in self.cooldown_locks:
            if now < self.cooldown_locks[lock_key]:
                return True
            else:
                del self.cooldown_locks[lock_key]
        return False

    def acquire_lock(self, lock_key: str, cooldown: float = LOCK_DOUBLE_COUNT_COOLDOWN):
        self.cooldown_locks[lock_key] = time.time() + cooldown

    def get_line_coords(self, width: int, height: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        if self.line_orientation == "horizontal":
            line_y = int(height * self.line_pos_ratio)
            return (0, line_y), (width, line_y)
        else:
            line_x = int(width * self.line_pos_ratio)
            return (line_x, 0), (line_x, height)

    def determine_side(self, cx: float, cy: float, width: int, height: int) -> str:
        if self.line_orientation == "horizontal":
            line_y = height * self.line_pos_ratio
            return "INSIDE" if cy > line_y else "OUTSIDE"
        else:
            line_x = width * self.line_pos_ratio
            return "INSIDE" if cx > line_x else "OUTSIDE"

    def process_crossing(self, track_id: int, cx: float, cy: float, width: int, height: int, person_info: Dict[str, Any]) -> Optional[str]:
        """
        Detects if this person crossed the entrance line between frames.
        Returns: 'IN', 'OUT', or None
        """
        now = time.time()
        current_side = self.determine_side(cx, cy, width, height)

        if track_id not in self.track_side:
            # First time seeing this track ID -> initialize starting side
            self.track_side[track_id] = current_side
            self.track_history[track_id] = [(cx, cy, now)]
            return None

        previous_side = self.track_side[track_id]
        self.track_history[track_id].append((cx, cy, now))
        
        # Keep recent 20 points
        if len(self.track_history[track_id]) > 20:
            self.track_history[track_id] = self.track_history[track_id][-20:]

        event_direction = None

        # Outside -> Inside = "IN" (Entering building)
        if previous_side == "OUTSIDE" and current_side == "INSIDE":
            event_direction = "IN"
        # Inside -> Outside = "OUT" (Exiting building)
        elif previous_side == "INSIDE" and current_side == "OUTSIDE":
            event_direction = "OUT"

        if event_direction:
            self.track_side[track_id] = current_side

            # Check Lock System (Anti-Double Counting)
            staff_id = person_info.get("staff_id")
            lock_key = f"staff_{staff_id}" if staff_id else f"track_{track_id}"

            if self.is_locked(lock_key):
                # Ignored because of recent crossing lock
                return None

            # Acquire lock
            self.acquire_lock(lock_key, LOCK_DOUBLE_COUNT_COOLDOWN)

            # Update stats
            if event_direction == "IN":
                self.count_in += 1
            else:
                self.count_out += 1

            now_str = datetime.now().strftime("%H:%M:%S")

            if person_info.get("is_registered"):
                # Registered Staff
                record_gate_event(
                    person_type="Registered",
                    direction=event_direction,
                    staff_id=staff_id,
                    confidence=person_info.get("confidence", 0.0),
                    snapshot_path=person_info.get("snapshot_path")
                )
                event_entry = {
                    "time": now_str,
                    "direction": event_direction,
                    "type": "registered",
                    "title": f"{person_info.get('name')} ({person_info.get('designation')})",
                    "code": person_info.get("staff_code"),
                    "badge": f"Gate {event_direction}",
                    "msg": f"Checked {event_direction} at {now_str}. Work timer {'started' if event_direction == 'IN' else 'stopped'}."
                }
            else:
                # Unknown Person
                self.count_unknown += 1
                snap_path = person_info.get("snapshot_path")
                full_snap_path = None
                if not snap_path and self.face_engine:
                    snap_path, full_snap_path = self.face_engine.save_unknown_snapshot(
                        face_crop=person_info.get("face_crop"),
                        portrait_crop=person_info.get("portrait_crop"),
                        full_frame=person_info.get("full_frame")
                    )
                    person_info["snapshot_path"] = snap_path
                    person_info["full_snap_path"] = full_snap_path
                else:
                    snap_path = snap_path or ""

                notes_text = f"full:{full_snap_path}" if full_snap_path else f"Unknown visitor {event_direction} at {now_str}"
                log_unknown_visitor(
                    snapshot_path=snap_path or "",
                    camera_id="Gate Cam 1",
                    notes=notes_text
                )
                event_entry = {
                    "time": now_str,
                    "direction": event_direction,
                    "type": "unknown",
                    "title": "⚠️ Unknown Visitor Detected",
                    "code": "UNREG-FACE",
                    "badge": "ALERT",
                    "snapshot": snap_path,
                    "msg": f"Unregistered person crossed gate {event_direction}. Snapshot archived."
                }

            self.recent_events.insert(0, event_entry)
            if len(self.recent_events) > 30:
                self.recent_events = self.recent_events[:30]

            return event_direction

        return None

    def draw_hud_overlay(self, frame: np.ndarray, detections: List[Dict[str, Any]], is_counting: bool = True) -> np.ndarray:
        """
        Draws the professional AI Camera HUD overlay on the video frame:
        - Cyberpunk/industrial gate line with glowing boundary
        - Direction arrows (OUTSIDE vs INSIDE OFFICE)
        - Bounding boxes with staff ID tags & designation
        - Top stats bar with FPS, Counts, and Date
        - Visual indicators for Active vs Paused/Stopped counting
        """
        h, w, _ = frame.shape
        overlay = frame.copy()

        # 1. Draw Gate Entrance Line
        pt1, pt2 = self.get_line_coords(w, h)
        
        # Soft zone rectangle along the line
        line_color = (0, 255, 255) if is_counting else (80, 110, 140)
        if self.line_orientation == "horizontal":
            line_y = pt1[1]
            cv2.line(overlay, pt1, pt2, line_color, 2)
            cv2.putText(overlay, "▲ ENTRANCE / OUTSIDE", (20, max(25, line_y - 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2)
            cv2.putText(overlay, "▼ OFFICE / MILL INTERIOR", (20, min(h - 15, line_y + 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 255, 100), 2)
        else:
            line_x = pt1[0]
            cv2.line(overlay, pt1, pt2, line_color, 2)
            cv2.putText(overlay, "◄ OUTSIDE", (max(10, line_x - 110), 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2)
            cv2.putText(overlay, "INSIDE ►", (min(w - 100, line_x + 15), 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (50, 255, 100), 2)

        # 2. Draw Person and Face Bounding Boxes
        for det in detections:
            is_reg = det.get("is_registered", False)
            fb = det.get("face_box", [0, 0, 0, 0])
            name = det.get("name", "Unknown")
            desig = det.get("designation", "")
            code = det.get("staff_code", "")
            fx1, fy1, fx2, fy2 = fb

            # Color scheme
            color = (40, 220, 80) if is_reg else (30, 70, 240)  # Green for registered, Red for unknown
            corner_len = 15

            # Face Box with modern industrial corners
            cv2.rectangle(overlay, (fx1, fy1), (fx2, fy2), color, 2)
            
            # Corner accents
            cv2.line(overlay, (fx1, fy1), (fx1 + corner_len, fy1), color, 3)
            cv2.line(overlay, (fx1, fy1), (fx1, fy1 + corner_len), color, 3)
            cv2.line(overlay, (fx2, fy1), (fx2 - corner_len, fy1), color, 3)
            cv2.line(overlay, (fx2, fy1), (fx2, fy1 + corner_len), color, 3)
            cv2.line(overlay, (fx1, fy2), (fx1 + corner_len, fy2), color, 3)
            cv2.line(overlay, (fx1, fy2), (fx1, fy2 - corner_len), color, 3)
            cv2.line(overlay, (fx2, fy2), (fx2 - corner_len, fy2), color, 3)
            cv2.line(overlay, (fx2, fy2), (fx2, fy2 - corner_len), color, 3)

            # Badge background
            label = f"[{code}] {name} - {desig}" if is_reg else "⚠️ UNKNOWN VISITOR"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 2)
            badge_y = max(th + 10, fy1 - 8)
            cv2.rectangle(overlay, (fx1, badge_y - th - 6), (fx1 + tw + 12, badge_y + 4), color, -1)
            cv2.putText(overlay, label, (fx1 + 6, badge_y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 0) if is_reg else (255, 255, 255), 2)

        # 3. Top Status HUD Bar
        hud_bg = overlay[0:45, 0:w]
        dark_bar = np.zeros_like(hud_bg)
        cv2.addWeighted(hud_bg, 0.2, dark_bar, 0.8, 0, hud_bg)
        overlay[0:45, 0:w] = hud_bg
        cv2.line(overlay, (0, 45), (w, 45), (60, 80, 100), 1)

        # Status text
        if is_counting:
            cam_tag = "🔴 LIVE GATE CAM 01 [24/7 AI ACTIVE]"
            tag_color = (80, 255, 120)
        else:
            cam_tag = "⏸️ VIDEO / COUNTING PAUSED [AI STANDBY]"
            tag_color = (0, 180, 255)

        cv2.putText(overlay, cam_tag, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, tag_color, 2)
        
        stats_str = f"IN: {self.count_in}  |  OUT: {self.count_out}  |  INSIDE: {max(0, self.count_in - self.count_out)}  |  UNKNOWN: {self.count_unknown}"
        (sw, _), _ = cv2.getTextSize(stats_str, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.putText(overlay, stats_str, (w - sw - 20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 240, 255), 2)

        # If paused, show center banner
        if not is_counting:
            banner_text = "COUNTING PAUSED - CLICK START TO RESUME"
            (bw, bh), _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 0.70, 2)
            bx = (w - bw) // 2
            by = h - 30
            cv2.rectangle(overlay, (bx - 16, by - bh - 10), (bx + bw + 16, by + 10), (20, 25, 35), -1)
            cv2.rectangle(overlay, (bx - 16, by - bh - 10), (bx + bw + 16, by + 10), (0, 180, 255), 2)
            cv2.putText(overlay, banner_text, (bx, by), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 210, 255), 2)

        return overlay
