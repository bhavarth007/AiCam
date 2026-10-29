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
        Gate line defined by two normalized endpoints (x1,y1) -> (x2,y2).
        Default: full-width horizontal line at 55% height.
        line_orientation kept for legacy compatibility.
        """
        self.line_orientation = line_orientation
        self.line_pos_ratio = line_pos_ratio
        self.face_engine = face_engine

        # Normalized line endpoints (0.0 - 1.0 of frame dimensions)
        # Default: horizontal full-width at 55%
        self.line_x1_norm: float = 0.0
        self.line_y1_norm: float = 0.55
        self.line_x2_norm: float = 1.0
        self.line_y2_norm: float = 0.55

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

    # ─── Line Configuration ──────────────────────────────────────────────────

    def set_line_position(self, ratio: float, orientation: Optional[str] = None):
        """Legacy: move a full-span horizontal or vertical line."""
        self.line_pos_ratio = max(0.05, min(0.95, ratio))
        if orientation in ["horizontal", "vertical"]:
            self.line_orientation = orientation

        if self.line_orientation == "horizontal":
            self.line_x1_norm = 0.0
            self.line_y1_norm = self.line_pos_ratio
            self.line_x2_norm = 1.0
            self.line_y2_norm = self.line_pos_ratio
        else:
            self.line_x1_norm = self.line_pos_ratio
            self.line_y1_norm = 0.0
            self.line_x2_norm = self.line_pos_ratio
            self.line_y2_norm = 1.0

    def set_line_coords(self, x1n: float, y1n: float, x2n: float, y2n: float):
        """
        Set arbitrary gate line endpoints as normalized (0.0-1.0) fractions.
        This supports any angle, any length, and any position on the frame.
        """
        self.line_x1_norm = max(0.0, min(1.0, x1n))
        self.line_y1_norm = max(0.0, min(1.0, y1n))
        self.line_x2_norm = max(0.0, min(1.0, x2n))
        self.line_y2_norm = max(0.0, min(1.0, y2n))

        # Derive legacy compat fields
        dx = abs(x2n - x1n)
        dy = abs(y2n - y1n)
        if dy > dx:
            self.line_orientation = "vertical"
            self.line_pos_ratio = (x1n + x2n) / 2.0
        else:
            self.line_orientation = "horizontal"
            self.line_pos_ratio = (y1n + y2n) / 2.0

    def get_line_pixel_coords(self, width: int, height: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """Returns absolute pixel coords for the gate line given frame dimensions."""
        x1 = int(self.line_x1_norm * width)
        y1 = int(self.line_y1_norm * height)
        x2 = int(self.line_x2_norm * width)
        y2 = int(self.line_y2_norm * height)
        return (x1, y1), (x2, y2)

    # Legacy compat alias
    def get_line_coords(self, width: int, height: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return self.get_line_pixel_coords(width, height)

    # ─── Side Detection ───────────────────────────────────────────────────────

    def _point_side_of_line(self, px: float, py: float,
                             x1: float, y1: float, x2: float, y2: float) -> str:
        """
        Returns 'INSIDE' or 'OUTSIDE' depending on which side of the
        directed line (x1,y1)->(x2,y2) the point (px,py) lies on.
        Uses the sign of the 2D cross product.
        """
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return "INSIDE" if cross >= 0 else "OUTSIDE"

    def determine_side(self, cx: float, cy: float, width: int, height: int) -> str:
        """Determine which side of the gate line the point (cx, cy) is on."""
        # Convert normalized line endpoints to pixels
        lx1 = self.line_x1_norm * width
        ly1 = self.line_y1_norm * height
        lx2 = self.line_x2_norm * width
        ly2 = self.line_y2_norm * height
        return self._point_side_of_line(cx, cy, lx1, ly1, lx2, ly2)

    # ─── Cooldown Lock System ─────────────────────────────────────────────────

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

    # ─── Crossing Detection ───────────────────────────────────────────────────

    def process_crossing(self, track_id: int, cx: float, cy: float,
                         width: int, height: int,
                         person_info: Dict[str, Any]) -> Optional[str]:
        """
        Detects if this person crossed the entrance gate line between frames.
        Returns: 'IN', 'OUT', or None
        """
        now = time.time()
        current_side = self.determine_side(cx, cy, width, height)

        if track_id not in self.track_side:
            self.track_side[track_id] = current_side
            self.track_history[track_id] = [(cx, cy, now)]
            return None

        previous_side = self.track_side[track_id]
        self.track_history[track_id].append((cx, cy, now))

        # Keep recent 20 points
        if len(self.track_history[track_id]) > 20:
            self.track_history[track_id] = self.track_history[track_id][-20:]

        event_direction = None

        # OUTSIDE -> INSIDE = "IN" (Entering building)
        if previous_side == "OUTSIDE" and current_side == "INSIDE":
            event_direction = "IN"
        # INSIDE -> OUTSIDE = "OUT" (Exiting building)
        elif previous_side == "INSIDE" and current_side == "OUTSIDE":
            event_direction = "OUT"

        if event_direction:
            self.track_side[track_id] = current_side

            # Anti-Double Counting Lock
            staff_id = person_info.get("staff_id")
            lock_key = f"staff_{staff_id}" if staff_id else f"track_{track_id}"

            if self.is_locked(lock_key):
                return None

            self.acquire_lock(lock_key, LOCK_DOUBLE_COUNT_COOLDOWN)

            if event_direction == "IN":
                self.count_in += 1
            else:
                self.count_out += 1

            now_str = datetime.now().strftime("%H:%M:%S")

            if person_info.get("is_registered"):
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

    # ─── HUD Overlay ─────────────────────────────────────────────────────────

    def draw_hud_overlay(self, frame: np.ndarray, detections: List[Dict[str, Any]],
                         is_counting: bool = True) -> np.ndarray:
        """
        Draws the professional AI Camera HUD overlay on the video frame:
        - Draggable arbitrary gate line with glowing effect and endpoint handles
        - Direction labels on each side
        - Bounding boxes with staff ID tags & designation
        - Top stats bar with FPS, Counts, and Date
        """
        h, w, _ = frame.shape
        overlay = frame.copy()

        # ── 1. Draw Gate Line (arbitrary endpoints) ──────────────────────────
        pt1, pt2 = self.get_line_pixel_coords(w, h)
        x1, y1 = pt1
        x2, y2 = pt2

        line_color      = (0, 255, 255) if is_counting else (80, 110, 140)
        glow_color      = (0, 180, 180) if is_counting else (50, 80, 100)
        handle_color    = (255, 200, 0) if is_counting else (100, 120, 140)

        # Glow effect - draw thick blurred lines behind
        cv2.line(overlay, pt1, pt2, glow_color, 8)
        cv2.line(overlay, pt1, pt2, line_color, 2)

        # Endpoint handles (draggable dots)
        cv2.circle(overlay, pt1, 9, handle_color, -1)
        cv2.circle(overlay, pt1, 9, (255, 255, 255), 2)
        cv2.circle(overlay, pt2, 9, handle_color, -1)
        cv2.circle(overlay, pt2, 9, (255, 255, 255), 2)

        # Midpoint center marker
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        cv2.circle(overlay, (mx, my), 6, (255, 255, 255), -1)
        cv2.circle(overlay, (mx, my), 6, line_color, 2)

        # Direction labels on each side of the line
        # Perpendicular direction for label placement
        dx, dy = x2 - x1, y2 - y1
        length = max(1, (dx * dx + dy * dy) ** 0.5)
        # Normal vector (perpendicular, pointing "INSIDE")
        nx, ny = -dy / length, dx / length

        # Offset labels 30px on each side
        offset = 36
        label_out_x = int(mx - nx * offset)
        label_out_y = int(my - ny * offset)
        label_in_x  = int(mx + nx * offset)
        label_in_y  = int(my + ny * offset)

        out_label = "▲ OUTSIDE / ENTRANCE"
        in_label  = "▼ INSIDE / OFFICE"
        (ow, oh), _ = cv2.getTextSize(out_label, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
        (iw, ih), _ = cv2.getTextSize(in_label,  cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)

        lox = max(4, min(w - ow - 4, label_out_x - ow // 2))
        loy = max(18, min(h - 6, label_out_y))
        lix = max(4, min(w - iw - 4, label_in_x - iw // 2))
        liy = max(18, min(h - 6, label_in_y))

        cv2.putText(overlay, out_label, (lox, loy), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 230, 255), 2, cv2.LINE_AA)
        cv2.putText(overlay, in_label,  (lix, liy), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (50, 255, 100), 2, cv2.LINE_AA)

        # ── 2. Person Bounding Boxes ─────────────────────────────────────────
        for det in detections:
            is_reg = det.get("is_registered", False)
            fb = det.get("face_box", [0, 0, 0, 0])
            name = det.get("name", "Unknown")
            desig = det.get("designation", "")
            code = det.get("staff_code", "")
            fx1, fy1, fx2, fy2 = [int(v) for v in fb]

            color = (40, 220, 80) if is_reg else (30, 70, 240)
            corner_len = 15

            cv2.rectangle(overlay, (fx1, fy1), (fx2, fy2), color, 2)
            # Corner accents
            for px, py, dpx, dpy in [
                (fx1, fy1, corner_len, 0), (fx1, fy1, 0, corner_len),
                (fx2, fy1, -corner_len, 0), (fx2, fy1, 0, corner_len),
                (fx1, fy2, corner_len, 0), (fx1, fy2, 0, -corner_len),
                (fx2, fy2, -corner_len, 0), (fx2, fy2, 0, -corner_len),
            ]:
                cv2.line(overlay, (px, py), (px + dpx, py + dpy), color, 3)

            label = f"[{code}] {name} - {desig}" if is_reg else "⚠️ UNKNOWN VISITOR"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.50, 2)
            badge_y = max(th + 10, fy1 - 8)
            cv2.rectangle(overlay, (fx1, badge_y - th - 6), (fx1 + tw + 12, badge_y + 4), color, -1)
            cv2.putText(overlay, label, (fx1 + 6, badge_y - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.50,
                        (0, 0, 0) if is_reg else (255, 255, 255), 2)

        # ── 3. Top Status HUD Bar ─────────────────────────────────────────────
        hud_bg = overlay[0:45, 0:w]
        dark_bar = np.zeros_like(hud_bg)
        cv2.addWeighted(hud_bg, 0.2, dark_bar, 0.8, 0, hud_bg)
        overlay[0:45, 0:w] = hud_bg
        cv2.line(overlay, (0, 45), (w, 45), (60, 80, 100), 1)

        if is_counting:
            cam_tag   = "LIVE GATE CAM 01 [24/7 AI ACTIVE]"
            tag_color = (80, 255, 120)
        else:
            cam_tag   = "VIDEO / COUNTING PAUSED [AI STANDBY]"
            tag_color = (0, 180, 255)

        cv2.putText(overlay, cam_tag, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, tag_color, 2)

        stats_str = (f"IN: {self.count_in}  |  OUT: {self.count_out}  |  "
                     f"INSIDE: {max(0, self.count_in - self.count_out)}  |  "
                     f"UNKNOWN: {self.count_unknown}")
        (sw, _), _ = cv2.getTextSize(stats_str, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.putText(overlay, stats_str, (w - sw - 20, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 240, 255), 2)

        # Paused banner
        if not is_counting:
            banner_text = "COUNTING PAUSED - CLICK START TO RESUME"
            (bw, bh), _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 0.70, 2)
            bx = (w - bw) // 2
            by = h - 30
            cv2.rectangle(overlay, (bx - 16, by - bh - 10), (bx + bw + 16, by + 10), (20, 25, 35), -1)
            cv2.rectangle(overlay, (bx - 16, by - bh - 10), (bx + bw + 16, by + 10), (0, 180, 255), 2)
            cv2.putText(overlay, banner_text, (bx, by),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 210, 255), 2)

        return overlay
