import os
import cv2
import torch
import torchvision.models as models
import torchvision.transforms as transforms
import numpy as np
from PIL import Image
from typing import Tuple, List, Optional, Dict, Any
from ultralytics import YOLO
from backend.config import BASE_DIR, MODELS_DIR, UNKNOWN_SNAPSHOTS_DIR, STAFF_PHOTOS_DIR, FACE_MATCH_THRESHOLD
from backend.database import get_staff_with_embeddings, log_unknown_visitor

class FaceRecognitionEngine:
    def __init__(self):
        print("[FaceEngine] Initializing YOLO-pose detector and MobileNetV3 feature extractor...")
        # 1. Load YOLOv8-pose for human and facial landmark detection
        self.pose_model = YOLO("yolov8n-pose.pt")
        
        # 2. Load PyTorch MobileNetV3 Small as deep feature extractor
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        weights = models.MobileNet_V3_Small_Weights.DEFAULT
        mobilenet = models.mobilenet_v3_small(weights=weights)
        
        # We use the feature backbone + pooling to produce a 576-dimensional embedding
        self.feature_extractor = mobilenet.features.to(self.device).eval()
        self.avgpool = torch.nn.AdaptiveAvgPool2d((1, 1)).to(self.device)
        
        # Standard PyTorch normalization for vision models
        self.transform = transforms.Compose([
            transforms.Resize((128, 128)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])
        
        # Cached registered embeddings
        self.registered_faces = []
        self.reload_registered_staff()
        print(f"[FaceEngine] Initialized successfully on {self.device}. Loaded {len(self.registered_faces)} staff embeddings.")

    def reload_registered_staff(self):
        """Reload staff list and cached face embeddings from database, including multi-angle reference photos."""
        import json
        staff_list = get_staff_with_embeddings()
        valid_staff = []

        ref_by_staff = {}
        try:
            from backend.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT staff_id, pose_type, face_embedding, quality_score FROM staff_reference_photos")
            for row in cursor.fetchall():
                sid = row["staff_id"]
                if row["face_embedding"]:
                    try:
                        vec = json.loads(row["face_embedding"])
                        np_vec = np.array(vec, dtype=np.float32)
                        norm = np.linalg.norm(np_vec)
                        if norm > 0:
                            np_vec /= norm
                        ref_by_staff.setdefault(sid, []).append(np_vec)
                    except Exception:
                        pass
            conn.close()
        except Exception as e:
            print(f"[FaceEngine] Error loading reference photos: {e}")

        for s in staff_list:
            embeddings = []
            if s.get("face_embedding") and len(s["face_embedding"]) > 0:
                np_vec = np.array(s["face_embedding"], dtype=np.float32)
                norm = np.linalg.norm(np_vec)
                if norm > 0:
                    np_vec /= norm
                embeddings.append(np_vec)
                s["embedding_np"] = np_vec

            sid = s.get("id")
            if sid in ref_by_staff:
                embeddings.extend(ref_by_staff[sid])

            if embeddings:
                s["multi_embeddings"] = embeddings
                valid_staff.append(s)

        self.registered_faces = valid_staff
        return len(self.registered_faces)

    def extract_face_box_from_keypoints(self, box: List[float], keypoints: np.ndarray, img_w: int, img_h: int) -> Tuple[int, int, int, int]:
        """
        Uses YOLO-pose keypoints (0: Nose, 1: Left Eye, 2: Right Eye, 3: Left Ear, 4: Right Ear)
        or upper 35% of person bounding box to get a robust face crop.
        """
        x1, y1, x2, y2 = box
        bw = x2 - x1
        bh = y2 - y1

        # Check if facial keypoints are available with confidence > 0.3
        face_kpts = keypoints[:5]  # nose, eyes, ears
        valid_kpts = [pt for pt in face_kpts if pt[2] > 0.30]

        if len(valid_kpts) >= 2:
            pts_x = [pt[0] for pt in valid_kpts]
            pts_y = [pt[1] for pt in valid_kpts]
            min_kx, max_kx = min(pts_x), max(pts_x)
            min_ky, max_ky = min(pts_y), max(pts_y)

            # Add margin around keypoints
            face_w = max_kx - min_kx
            face_h = max_ky - min_ky
            margin_x = max(face_w * 0.6, bw * 0.20)
            margin_y = max(face_h * 0.8, bh * 0.15)

            fx1 = max(0, int(min_kx - margin_x))
            fy1 = max(0, int(min_ky - margin_y))
            fx2 = min(img_w, int(max_kx + margin_x))
            fy2 = min(img_h, int(max_ky + margin_y * 1.2))
        else:
            # Fallback to upper 35% of person bounding box
            fx1 = max(0, int(x1))
            fy1 = max(0, int(y1))
            fx2 = min(img_w, int(x2))
            fy2 = min(img_h, int(y1 + bh * 0.38))

        # Ensure valid area
        if fx2 <= fx1 + 10 or fy2 <= fy1 + 10:
            fx1, fy1, fx2, fy2 = int(x1), int(y1), int(x2), int(y1 + bh * 0.4)

        return fx1, fy1, fx2, fy2

    def compute_embedding(self, face_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Computes a 576-D L2-normalized feature embedding from face BGR image."""
        if face_bgr is None or face_bgr.size == 0 or face_bgr.shape[0] < 15 or face_bgr.shape[1] < 15:
            return None

        try:
            # Convert BGR to RGB PIL Image
            face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(face_rgb)
            tensor = self.transform(pil_img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                features = self.feature_extractor(tensor)
                pooled = self.avgpool(features).flatten()
                emb = pooled.cpu().numpy().astype(np.float32)

            # L2 normalize
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            return emb
        except Exception as e:
            print(f"[FaceEngine] Error computing embedding: {e}")
            return None

    def match_face(self, face_emb: np.ndarray) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Matches a face embedding against all registered staff embeddings using Cosine Similarity.
        Returns: (matched_staff_dict_or_None, similarity_score)
        """
        if face_emb is None or len(self.registered_faces) == 0:
            return None, 0.0

        best_score = -1.0
        best_match = None

        for staff in self.registered_faces:
            # Multi-angle search: evaluates front, left, right, upper, lower poses
            for ref_emb in staff.get("multi_embeddings", [staff.get("embedding_np")]):
                if ref_emb is not None:
                    sim = float(np.dot(face_emb, ref_emb))
                    if sim > best_score:
                        best_score = sim
                        best_match = staff

        # Threshold check
        if best_score >= FACE_MATCH_THRESHOLD and best_match is not None:
            return best_match, best_score
        return None, max(0.0, best_score)

    def process_person_detection(self, frame: np.ndarray, person_box: List[float], keypoints: np.ndarray, capture_unknown: bool = False) -> Dict[str, Any]:
        """
        Analyzes a single detected person, extracts face, recognizes staff or identifies unknown.
        """
        h, w, _ = frame.shape
        fx1, fy1, fx2, fy2 = self.extract_face_box_from_keypoints(person_box, keypoints, w, h)
        face_crop = frame[fy1:fy2, fx1:fx2]

        emb = self.compute_embedding(face_crop)
        matched_staff, sim = self.match_face(emb)

        # High-definition portrait crop (head to upper chest with generous margin)
        px1, py1, px2, py2 = person_box
        bw = max(1.0, px2 - px1)
        bh = max(1.0, py2 - py1)
        margin_x = bw * 0.22
        port_x1 = max(0, int(px1 - margin_x))
        port_x2 = min(w, int(px2 + margin_x))
        port_y1 = max(0, int(py1 - bh * 0.06))
        port_y2 = min(h, int(py1 + bh * 0.72))
        portrait_crop = frame[port_y1:port_y2, port_x1:port_x2]
        if portrait_crop.size == 0:
            portrait_crop = face_crop

        result = {
            "face_box": [fx1, fy1, fx2, fy2],
            "confidence": sim,
            "is_registered": False,
            "staff_id": None,
            "staff_code": None,
            "name": "Unknown Person",
            "designation": "Visitor / Unregistered",
            "snapshot_path": None,
            "face_crop": face_crop,
            "portrait_crop": portrait_crop,
            "full_frame": frame.copy()
        }

        if matched_staff:
            result["is_registered"] = True
            result["staff_id"] = matched_staff["id"]
            result["staff_code"] = matched_staff["staff_code"]
            result["name"] = matched_staff["name"]
            result["designation"] = matched_staff["designation"]
        elif capture_unknown and face_crop.size > 0:
            port_url, _ = self.save_unknown_snapshot(face_crop, portrait_crop, frame)
            result["snapshot_path"] = port_url

        return result

    def save_unknown_snapshot(self, face_crop: np.ndarray, portrait_crop: Optional[np.ndarray] = None, full_frame: Optional[np.ndarray] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Saves crystal-clear 4K / Ultra-HD unknown person snapshots into date folder:
        1. High-definition framed portrait crop (face, hair, shoulders, clothing).
        2. Full-frame 4K contextual gate shot.
        Returns: (portrait_url, full_frame_url)
        """
        primary_crop = portrait_crop if (portrait_crop is not None and portrait_crop.size > 0) else face_crop
        if primary_crop is None or primary_crop.size == 0:
            return None, None

        import uuid
        from datetime import datetime
        today_folder_name = datetime.now().strftime("%Y-%m-%d")
        today_dir = UNKNOWN_SNAPSHOTS_DIR / today_folder_name
        today_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime('%H%M%S')
        uid = uuid.uuid4().hex[:6]
        snap_name = f"unknown_{stamp}_{uid}.jpg"
        snap_path = today_dir / snap_name

        # Ensure high clarity: upscale small crops cleanly using Lanczos-4
        save_img = primary_crop
        ph, pw = save_img.shape[:2]
        if pw < 500 or ph < 500:
            scale = max(500.0 / pw, 500.0 / ph)
            new_w, new_h = int(pw * scale), int(ph * scale)
            save_img = cv2.resize(save_img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # Apply subtle unsharp masking for crystal-clear facial contours (eliminates camera softness and blur)
        try:
            gaussian = cv2.GaussianBlur(save_img, (0, 0), 2.0)
            save_img = cv2.addWeighted(save_img, 1.3, gaussian, -0.3, 0)
        except Exception:
            pass

        portrait_url = None
        try:
            cv2.imwrite(str(snap_path), save_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            portrait_url = f"/data/unknown_snapshots/{today_folder_name}/{snap_name}"
        except Exception as e:
            print(f"[FaceEngine] Error saving unknown snapshot: {e}")

        # Save full-frame 4K gate view for fullscreen inspection
        full_url = None
        if full_frame is not None and full_frame.size > 0:
            full_name = f"unknown_{stamp}_{uid}_full.jpg"
            full_path = today_dir / full_name
            try:
                cv2.imwrite(str(full_path), full_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                full_url = f"/data/unknown_snapshots/{today_folder_name}/{full_name}"
            except Exception as e:
                print(f"[FaceEngine] Error saving full frame: {e}")

        return portrait_url, full_url

    def register_staff_face(self, image_bgr: np.ndarray) -> Tuple[bool, Optional[List[float]], Optional[np.ndarray], str]:
        """
        Extracts face embedding from a photo or snapshot during Staff Registration.
        Returns: (success, embedding_list, cropped_face_bgr, message)
        """
        if image_bgr is None or image_bgr.size == 0:
            return False, None, None, "Invalid image data provided."

        h, w, _ = image_bgr.shape
        face_crop = image_bgr

        # If image is already a cropped face (e.g. from unknown visitor snapshot)
        if h <= 350 and w <= 350:
            face_crop = image_bgr
            emb = self.compute_embedding(face_crop)
            if emb is not None:
                return True, emb.tolist(), face_crop, "Face features successfully extracted from snapshot."

        # If full-body or larger photo, try YOLO-pose detection
        try:
            results = self.pose_model(image_bgr, verbose=False)
            if len(results) > 0 and len(results[0].boxes) > 0:
                box = results[0].boxes.xyxy[0].cpu().numpy().tolist()
                kpts = results[0].keypoints.data[0].cpu().numpy()
                fx1, fy1, fx2, fy2 = self.extract_face_box_from_keypoints(box, kpts, w, h)
                face_crop = image_bgr[fy1:fy2, fx1:fx2]
        except Exception as e:
            print(f"[FaceEngine] Pose detection warning during registration: {e}")

        # Compute embedding
        emb = self.compute_embedding(face_crop)
        if emb is None:
            # Fallback to full image directly
            emb = self.compute_embedding(image_bgr)
            face_crop = image_bgr

        if emb is None:
            return False, None, None, "Could not extract facial features. Please ensure good lighting and face visibility."

        return True, emb.tolist(), face_crop, "Face features successfully extracted and verified."
