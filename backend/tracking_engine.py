import time
import cv2
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from backend.config import LOCK_DOUBLE_COUNT_COOLDOWN, LINE_CROSSING_BUFFER
from backend.database import record_gate_event, log_unknown_visitor


class GateTrackingEngine:
    def __init__(self, line_orientation: str = "horizontal", line_pos_ratio: float = 0.55, face_engine=None):
        self.face_engine = face_engine

        # Geometry mode: 'polygon' (default 4-point door quad), 'box', or 'line'
        self.geometry_mode = "polygon"

        # 4-Point Door Quadrilateral (Normalized 0.0 - 1.0)
        # Default tuned precisely for testing video doorway perspective:
        # P1: Top-Left, P2: Top-Right, P3: Bottom-Right (Threshold Right), P4: Bottom-Left (Threshold Left)
        self.door_polygon = [
            {"x": 0.120, "y": 0.100},  # P1: Top-Left
            {"x": 0.440, "y": 0.100},  # P2: Top-Right
            {"x": 0.440, "y": 0.520},  # P3: Bottom-Right (Threshold Right)
            {"x": 0.120, "y": 0.520}   # P4: Bottom-Left (Threshold Left)
        ]

        # Invert IN vs OUT if camera is mounted from inside looking out
        self.flip_direction = False

        # Legacy Door Box representation
        self.door_box = {"x": 0.120, "y": 0.100, "w": 0.320, "h": 0.420}

        # Legacy Tripwire Line endpoints
        self.line_orientation = line_orientation
        self.line_pos_ratio = line_pos_ratio
        self.line_x1_norm: float = 0.120
        self.line_y1_norm: float = 0.520
        self.line_x2_norm: float = 0.440
        self.line_y2_norm: float = 0.520

        # Track history: {track_id: [(cx, cy, timestamp), ...]}
        self.track_history: Dict[int, List[Tuple[float, float, float]]] = {}

        # Track identity memory: {track_id: registered_person_info}
        self.track_identities: Dict[int, Dict[str, Any]] = {}

        # Track side status: {track_id: 'OUTSIDE' | 'INSIDE'}
        self.track_side: Dict[int, str] = {}

        # Anti-double count cooldown: {key: timestamp}
        self.cooldown_locks: Dict[str, float] = {}

        # Session Counters
        self.count_in = 0
        self.count_out = 0
        self.count_unknown = 0

        # Recent live event feed for UI
        self.recent_events: List[Dict[str, Any]] = []

    # ─── Geometry & Polygon Configuration ─────────────────────────────────────

    def set_door_polygon(self, points: List[Dict[str, float]], flip_direction: bool = False):
        """
        Sets arbitrary 4-point quadrilateral for the door.
        Points: [P1(TL), P2(TR), P3(BR), P4(BL)] normalized between 0.0 and 1.0.
        """
        if len(points) == 4:
            self.door_polygon = [
                {
                    "x": max(0.0, min(1.0, float(p.get("x", 0.0)))),
                    "y": max(0.0, min(1.0, float(p.get("y", 0.0))))
                }
                for p in points
            ]
            self.geometry_mode = "polygon"
            self.flip_direction = bool(flip_direction)

            # Update threshold line (P4 -> P3)
            p4 = self.door_polygon[3]
            p3 = self.door_polygon[2]
            self.line_x1_norm = p4["x"]
            self.line_y1_norm = p4["y"]
            self.line_x2_norm = p3["x"]
            self.line_y2_norm = p3["y"]

            # Update bounding box representation
            xs = [p["x"] for p in self.door_polygon]
            ys = [p["y"] for p in self.door_polygon]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            self.door_box = {
                "x": min_x,
                "y": min_y,
                "w": max(0.05, max_x - min_x),
                "h": max(0.05, max_y - min_y)
            }

    def get_door_polygon(self) -> Dict[str, Any]:
        """Returns the current 4-point door polygon and settings."""
        return {
            "polygon": self.door_polygon,
            "flip_direction": self.flip_direction,
            "geometry_mode": self.geometry_mode,
            "threshold_line": {
                "x1": self.line_x1_norm,
                "y1": self.line_y1_norm,
                "x2": self.line_x2_norm,
                "y2": self.line_y2_norm
            }
        }

    def set_geometry_mode(self, mode: str):
        self.geometry_mode = mode if mode in ["polygon", "box", "line"] else "polygon"

    def set_door_box(self, x: float, y: float, w: float, h: float):
        """Sets rigid door box and updates door polygon corners."""
        self.door_box = {
            "x": max(0.0, min(0.95, x)),
            "y": max(0.0, min(0.95, y)),
            "w": max(0.05, min(0.95, w)),
            "h": max(0.05, min(0.95, h))
        }
        bx, by, bw, bh = self.door_box["x"], self.door_box["y"], self.door_box["w"], self.door_box["h"]
        self.door_polygon = [
            {"x": bx, "y": by},
            {"x": bx + bw, "y": by},
            {"x": bx + bw, "y": by + bh},
            {"x": bx, "y": by + bh}
        ]
        self.line_x1_norm = bx
        self.line_y1_norm = by + bh
        self.line_x2_norm = bx + bw
        self.line_y2_norm = by + bh

    def set_line_coords(self, x1n: float, y1n: float, x2n: float, y2n: float):
        """Sets arbitrary tripwire line endpoints as normalized fractions."""
        self.line_x1_norm = max(0.0, min(1.0, x1n))
        self.line_y1_norm = max(0.0, min(1.0, y1n))
        self.line_x2_norm = max(0.0, min(1.0, x2n))
        self.line_y2_norm = max(0.0, min(1.0, y2n))
        self.geometry_mode = "line"

    def set_line_position(self, ratio: float, orientation: Optional[str] = None):
        """Legacy helper for single slider line position."""
        self.line_pos_ratio = max(0.05, min(0.95, ratio))
        if orientation in ["horizontal", "vertical"]:
            self.line_orientation = orientation
        if self.line_orientation == "horizontal":
            self.set_line_coords(0.0, self.line_pos_ratio, 1.0, self.line_pos_ratio)
        else:
            self.set_line_coords(self.line_pos_ratio, 0.0, self.line_pos_ratio, 1.0)

    def get_line_pixel_coords(self, width: int, height: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        x1 = int(self.line_x1_norm * width)
        y1 = int(self.line_y1_norm * height)
        x2 = int(self.line_x2_norm * width)
        y2 = int(self.line_y2_norm * height)
        return (x1, y1), (x2, y2)

    def get_line_coords(self, width: int, height: int) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        return self.get_line_pixel_coords(width, height)

    # ─── Side & Crossing Detection ────────────────────────────────────────────

    def _point_side_of_line(self, px: float, py: float,
                             x1: float, y1: float, x2: float, y2: float) -> str:
        """
        Calculates which side of the directed line (x1,y1)->(x2,y2) the point lies on.
        Uses 2D cross product:
        (x2 - x1)*(py - y1) - (y2 - y1)*(px - x1)
        """
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return "INSIDE" if cross >= 0 else "OUTSIDE"

    def determine_side_and_validity(self, cx: float, cy: float, width: int, height: int) -> Tuple[str, bool]:
        """
        Determines the side of the door borderline (INSIDE or OUTSIDE)
        and checks if the person is within the doorway lateral bounds / corridor.
        Returns: (side: 'INSIDE'|'OUTSIDE', is_in_door_corridor: bool)
        """
        if self.geometry_mode in ["polygon", "box"]:
            # Threshold borderline: P4 -> P3 (bottom edge across door threshold)
            p4 = self.door_polygon[3]
            p3 = self.door_polygon[2]
            lx1 = p4["x"] * width
            ly1 = p4["y"] * height
            lx2 = p3["x"] * width
            ly2 = p3["y"] * height

            side = self._point_side_of_line(cx, cy, lx1, ly1, lx2, ly2)

            # Lateral boundary projection: Ensure person passes through doorway opening
            dx = lx2 - lx1
            dy = ly2 - ly1
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq > 0:
                t = ((cx - lx1) * dx + (cy - ly1) * dy) / seg_len_sq
                # Generous corridor tolerance [-0.25 to 1.25] covers walking through door edges
                is_in_corridor = (-0.25 <= t <= 1.25)
            else:
                is_in_corridor = True

            return side, is_in_corridor
        else:
            # Standalone Tripwire Line mode
            lx1 = self.line_x1_norm * width
            ly1 = self.line_y1_norm * height
            lx2 = self.line_x2_norm * width
            ly2 = self.line_y2_norm * height
            side = self._point_side_of_line(cx, cy, lx1, ly1, lx2, ly2)

            dx = lx2 - lx1
            dy = ly2 - ly1
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq > 0:
                t = ((cx - lx1) * dx + (cy - ly1) * dy) / seg_len_sq
                is_in_corridor = (-0.15 <= t <= 1.15)
            else:
                is_in_corridor = True

            return side, is_in_corridor

    def determine_side(self, cx: float, cy: float, width: int, height: int) -> str:
        side, _ = self.determine_side_and_validity(cx, cy, width, height)
        return side

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
                          person_info: Dict[str, Any],
                          record_mode: str = "live") -> Optional[str]:
        """
        Detects if this person crossed the entrance door borderline between frames.
        Returns: 'IN', 'OUT', or None.
        Isolates records by record_mode ('live' or 'test').
        """
        now = time.time()
        current_side, in_corridor = self.determine_side_and_validity(cx, cy, width, height)

        # Remember and propagate confirmed staff identity across the entire track lifetime
        if person_info.get("is_registered"):
            prev = self.track_identities.get(track_id)
            if not prev or person_info.get("confidence", 0) >= prev.get("confidence", 0):
                self.track_identities[track_id] = dict(person_info)
        elif track_id in self.track_identities:
            saved = self.track_identities[track_id]
            person_info["is_registered"] = True
            person_info["name"] = saved["name"]
            person_info["staff_id"] = saved["staff_id"]
            person_info["staff_code"] = saved["staff_code"]
            person_info["designation"] = saved["designation"]
            person_info["confidence"] = max(person_info.get("confidence", 0.0), saved.get("confidence", 0.0))

        if track_id not in self.track_side:
            self.track_side[track_id] = current_side
            self.track_history[track_id] = [(cx, cy, now)]
            return None

        previous_side = self.track_side[track_id]
        self.track_history[track_id].append((cx, cy, now))
        if len(self.track_history[track_id]) > 25:
            self.track_history[track_id] = self.track_history[track_id][-25:]

        event_direction = None

        # Detect side flip if person was in or near the doorway corridor
        if previous_side != current_side and in_corridor:
            if previous_side == "OUTSIDE" and current_side == "INSIDE":
                event_direction = "OUT" if self.flip_direction else "IN"
            elif previous_side == "INSIDE" and current_side == "OUTSIDE":
                event_direction = "IN" if self.flip_direction else "OUT"

        if event_direction:
            self.track_side[track_id] = current_side

            # Anti-Double Counting Lock (checks track_id AND staff_id)
            staff_id = person_info.get("staff_id")
            track_lock = f"track_{track_id}"
            staff_lock = f"staff_{staff_id}" if staff_id else None

            if self.is_locked(track_lock) or (staff_lock and self.is_locked(staff_lock)):
                return None

            self.acquire_lock(track_lock, LOCK_DOUBLE_COUNT_COOLDOWN)
            if staff_lock:
                self.acquire_lock(staff_lock, LOCK_DOUBLE_COUNT_COOLDOWN)

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
                    snapshot_path=person_info.get("snapshot_path"),
                    record_mode=record_mode
                )
                event_entry = {
                    "time": now_str,
                    "direction": event_direction,
                    "type": "registered",
                    "record_mode": record_mode,
                    "title": f"{person_info.get('name')} ({person_info.get('designation')})",
                    "code": person_info.get("staff_code"),
                    "badge": f"Gate {event_direction}",
                    "msg": f"Checked {event_direction} at {now_str} [{record_mode.upper()}]. Work timer {'started' if event_direction == 'IN' else 'stopped'}."
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
                    notes=notes_text,
                    record_mode=record_mode
                )
                event_entry = {
                    "time": now_str,
                    "direction": event_direction,
                    "type": "unknown",
                    "record_mode": record_mode,
                    "title": "⚠️ Unknown Visitor Detected",
                    "code": "UNREG-FACE",
                    "badge": "ALERT",
                    "snapshot": snap_path,
                    "msg": f"Unregistered person crossed door {event_direction} [{record_mode.upper()}]. Snapshot archived."
                }

            self.recent_events.insert(0, event_entry)
            if len(self.recent_events) > 40:
                self.recent_events = self.recent_events[:40]

            return event_direction

        # Update current side even if not crossing
        self.track_side[track_id] = current_side
        return None

    # ─── HUD Overlay ─────────────────────────────────────────────────────────

    def draw_hud_overlay(self, frame: np.ndarray, detections: List[Dict[str, Any]],
                         is_counting: bool = True, record_mode: str = "live") -> np.ndarray:
        """
        Draws the professional AI Camera HUD overlay on the video frame:
        - 4-Corner Door Quad polygon with semi-transparent fill
        - Glowing doorway threshold borderline with IN/OUT direction labels
        - 4 corner handles (P1, P2, P3, P4)
        - Person bounding boxes with Staff Face ID badges
        - Top HUD bar with real-time stats and mode badge
        """
        h, w, _ = frame.shape
        overlay = frame.copy()

        # ── 1. Draw Door Polygon (4 Editable Corners) ───────────────────────
        poly_pts = np.array([
            [int(p["x"] * w), int(p["y"] * h)]
            for p in self.door_polygon
        ], dtype=np.int32)

        # Draw semi-transparent fill inside door zone
        door_fill = overlay.copy()
        cv2.fillPoly(door_fill, [poly_pts], (40, 60, 20) if is_counting else (30, 40, 45))
        cv2.addWeighted(door_fill, 0.28, overlay, 0.72, 0, overlay)

        # Door frame outline
        frame_color = (0, 220, 255) if is_counting else (80, 110, 130)
        cv2.polylines(overlay, [poly_pts], True, frame_color, 2, cv2.LINE_AA)

        # ── 2. Draw Threshold Borderline (P4 -> P3) ─────────────────────────
        pt4 = (int(self.door_polygon[3]["x"] * w), int(self.door_polygon[3]["y"] * h))
        pt3 = (int(self.door_polygon[2]["x"] * w), int(self.door_polygon[2]["y"] * h))

        line_color = (0, 255, 120) if is_counting else (100, 140, 100)
        glow_color = (0, 180, 80) if is_counting else (50, 80, 50)

        # Glowing line effect
        cv2.line(overlay, pt4, pt3, glow_color, 8, cv2.LINE_AA)
        cv2.line(overlay, pt4, pt3, line_color, 3, cv2.LINE_AA)

        # Midpoint on threshold line
        mx = (pt4[0] + pt3[0]) // 2
        my = (pt4[1] + pt3[1]) // 2
        cv2.circle(overlay, (mx, my), 6, (255, 255, 255), -1)
        cv2.circle(overlay, (mx, my), 6, line_color, 2)

        # Threshold Direction Labels
        dx = pt3[0] - pt4[0]
        dy = pt3[1] - pt4[1]
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = -dy / length, dx / length
        offset = 32

        label_in_dir = "▲ IN" if not self.flip_direction else "▼ OUT"
        label_out_dir = "▼ OUT" if not self.flip_direction else "▲ IN"
        cv2.putText(overlay, f"{label_in_dir} (DOOR)", (int(mx + nx * offset) - 30, int(my + ny * offset)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (50, 255, 120), 2, cv2.LINE_AA)
        cv2.putText(overlay, f"{label_out_dir} (EXIT)", (int(mx - nx * offset) - 30, int(my - nx * offset)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 220, 255), 2, cv2.LINE_AA)

        # ── 3. Draw 4 Corner Handles (P1, P2, P3, P4) ───────────────────────
        handle_names = ["P1 (TL)", "P2 (TR)", "P3 (BR)", "P4 (BL)"]
        for idx, p in enumerate(self.door_polygon):
            px = int(p["x"] * w)
            py = int(p["y"] * h)
            # Handle circle with glow
            cv2.circle(overlay, (px, py), 9, (255, 200, 0) if is_counting else (120, 130, 140), -1)
            cv2.circle(overlay, (px, py), 9, (255, 255, 255), 2)
            cv2.circle(overlay, (px, py), 3, (0, 0, 0), -1)

            # Label next to corner handle
            lbl = handle_names[idx]
            lx = max(5, min(w - 65, px + 12 if idx in [1, 2] else px - 60))
            ly = max(18, min(h - 10, py - 10 if idx in [0, 1] else py + 20))
            cv2.putText(overlay, lbl, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

        # ── 4. Person Bounding Boxes & Biometrics ───────────────────────────
        for det in detections:
            is_reg = det.get("is_registered", False)
            fb = det.get("face_box", [0, 0, 0, 0])
            name = det.get("name", "Unknown Person")
            desig = det.get("designation", "")
            code = det.get("staff_code", "")
            conf = det.get("confidence", 0.0)
            fx1, fy1, fx2, fy2 = [int(v) for v in fb]

            color = (40, 220, 80) if is_reg else (30, 70, 240)
            corner_len = 14

            cv2.rectangle(overlay, (fx1, fy1), (fx2, fy2), color, 2)
            # Corner accents
            for cx_p, cy_p, dcx, dcy in [
                (fx1, fy1, corner_len, 0), (fx1, fy1, 0, corner_len),
                (fx2, fy1, -corner_len, 0), (fx2, fy1, 0, corner_len),
                (fx1, fy2, corner_len, 0), (fx1, fy2, 0, -corner_len),
                (fx2, fy2, -corner_len, 0), (fx2, fy2, 0, -corner_len),
            ]:
                cv2.line(overlay, (cx_p, cy_p), (cx_p + dcx, cy_p + dcy), color, 3)

            label = f"[{code}] {name} ({conf:.0%})" if is_reg else f"⚠️ UNKNOWN VISITOR ({conf:.0%})"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 2)
            badge_y = max(th + 10, fy1 - 8)
            cv2.rectangle(overlay, (fx1, badge_y - th - 6), (fx1 + tw + 12, badge_y + 4), color, -1)
            cv2.putText(overlay, label, (fx1 + 6, badge_y - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                        (0, 0, 0) if is_reg else (255, 255, 255), 2)

        # ── 5. Top Status HUD Bar ─────────────────────────────────────────────
        hud_bg = overlay[0:45, 0:w]
        dark_bar = np.zeros_like(hud_bg)
        cv2.addWeighted(hud_bg, 0.2, dark_bar, 0.8, 0, hud_bg)
        overlay[0:45, 0:w] = hud_bg
        cv2.line(overlay, (0, 45), (w, 45), (60, 80, 100), 1)

        mode_badge = "🧪 TEST VIDEO MODE" if record_mode == "test" else "🔴 LIVE CAMERA 01"
        status_tag = f"{mode_badge} [24/7 AI ACTIVE]" if is_counting else f"{mode_badge} [PAUSED]"
        tag_color = (0, 220, 255) if record_mode == "test" else (80, 255, 120)

        cv2.putText(overlay, status_tag, (15, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, tag_color, 2)

        stats_str = (f"IN: {self.count_in}  |  OUT: {self.count_out}  |  "
                     f"INSIDE: {max(0, self.count_in - self.count_out)}  |  "
                     f"UNKNOWN: {self.count_unknown}")
        (sw, _), _ = cv2.getTextSize(stats_str, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 2)
        cv2.putText(overlay, stats_str, (w - sw - 20, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 240, 255), 2)

        if not is_counting:
            banner_text = "COUNTING PAUSED - CLICK START TO RESUME"
            (bw, bh), _ = cv2.getTextSize(banner_text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            bx = (w - bw) // 2
            by = h - 28
            cv2.rectangle(overlay, (bx - 16, by - bh - 10), (bx + bw + 16, by + 10), (20, 25, 35), -1)
            cv2.rectangle(overlay, (bx - 16, by - bh - 10), (bx + bw + 16, by + 10), (0, 180, 255), 2)
            cv2.putText(overlay, banner_text, (bx, by),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 210, 255), 2)

        return overlay
