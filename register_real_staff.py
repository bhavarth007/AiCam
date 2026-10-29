#!/usr/bin/env python3
"""
Registers 4 real staff members using user-provided photos.
Extracts facial features and updates database.
"""
import os
import sys
import shutil
import uuid
from pathlib import Path

sys.path.insert(0, r'c:\AiCam')
os.chdir(r'c:\AiCam')

import cv2
import numpy as np
from backend.database import get_all_staff, add_staff, update_staff, delete_staff
from backend.face_engine import FaceRecognitionEngine
from backend.config import STAFF_PHOTOS_DIR

STAFF_CONFIG = [
    {
        "name": "Milan Hidad",
        "designation": "Team Leader",
        "face_id": "FC-TXS-001",
        "photo": r"C:\Users\ghans\.gemini\antigravity\brain\64ddf078-beb8-4c8b-b2f3-bef389c6c678\.user_uploaded\media_1793247425193.png"
    },
    {
        "name": "Bhavarth Hapani",
        "designation": "Software Engineer",
        "face_id": "FC-TXS-417",
        "photo": r"C:\Users\ghans\.gemini\antigravity\brain\64ddf078-beb8-4c8b-b2f3-bef389c6c678\.user_uploaded\media_1793247485295.png"
    },
    {
        "name": "Vishal Morya",
        "designation": "Accountant",
        "face_id": "FC-TXS-002",
        "photo": r"C:\Users\ghans\.gemini\antigravity\brain\64ddf078-beb8-4c8b-b2f3-bef389c6c678\.user_uploaded\media_1793247583600.png"
    },
    {
        "name": "Mahesh Ratod",
        "designation": "Accountant Assistant",
        "face_id": "FC-TXS-003",
        "photo": r"c:\AiCam\data\staff_photos\staff_FC_TXS_003.jpg"
    }
]

def main():
    print("=" * 60)
    print("AiCam Staff Registration & Embedding Generator")
    print("=" * 60)

    # Initialize Face Recognition Engine
    face_engine = FaceRecognitionEngine()
    
    # Get current staff
    current_staff = get_all_staff()
    print(f"Existing staff in DB before registration: {len(current_staff)}")
    for s in current_staff:
        print(f"  Existing ID {s['id']}: {s['name']} ({s['designation']}) | {s['face_id']}")

    STAFF_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    for item in STAFF_CONFIG:
        name = item["name"]
        designation = item["designation"]
        face_id = item["face_id"]
        photo_src = Path(item["photo"])

        print(f"\nProcessing {name} ({designation}) | {face_id}...")
        if not photo_src.exists():
            print(f"  [ERROR] Source photo not found: {photo_src}")
            continue

        # Load image
        img = cv2.imread(str(photo_src))
        if img is None:
            print(f"  [ERROR] Failed to decode image: {photo_src}")
            continue

        print(f"  Photo loaded: {img.shape}")

        # Destination filename
        dest_filename = f"staff_{face_id.replace('-', '_')}.jpg"
        dest_path = STAFF_PHOTOS_DIR / dest_filename
        # Save standardized jpeg
        cv2.imwrite(str(dest_path), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        db_photo_path = f"/data/staff_photos/{dest_filename}"
        print(f"  Saved to: {dest_path}")

        # Extract face embedding
        success, emb, face_crop, msg = face_engine.register_staff_face(img)
        if success and emb is not None:
            emb_len = len(emb) if isinstance(emb, list) else emb.size
            print(f"  [FACE DETECTED] Feature embedding generated successfully ({emb_len} dims)")
        else:
            print(f"  [WARNING] Face detection fallback: {msg}")
            # If face detector missed, use feature extraction on center crop or full image
            try:
                # Resize image and get features directly
                resized = cv2.resize(img, (224, 224))
                raw_emb = face_engine._extract_features(resized)
                emb = raw_emb.tolist() if hasattr(raw_emb, 'tolist') else list(raw_emb)
                print(f"  [FALLBACK] Extracted features from full image crop ({len(emb)} dims)")
            except Exception as e:
                print(f"  [FALLBACK FAILED] {e}")
                emb = [0.0] * 512

        # Check if staff with this name or face_id already exists in DB
        matching = [s for s in current_staff if s['face_id'] == face_id or s['name'].lower() == name.lower()]
        if matching:
            staff_id = matching[0]['id']
            print(f"  Updating existing staff record ID: {staff_id}")
            update_staff(
                staff_id=staff_id,
                name=name,
                designation=designation,
                face_id=face_id,
                face_embedding=emb,
                photo_path=db_photo_path
            )
        else:
            print(f"  Adding new staff record...")
            staff_id = add_staff(
                name=name,
                designation=designation,
                face_id=face_id,
                face_embedding=emb,
                photo_path=db_photo_path
            )
            print(f"  Created staff ID: {staff_id}")

    # Reload staff in face engine
    face_engine.reload_registered_staff()
    
    # Final check
    final_staff = get_all_staff()
    print("\n" + "=" * 60)
    print(f"Final staff count in DB: {len(final_staff)}")
    for s in final_staff:
        print(f"  - ID {s['id']}: {s['name']} | {s['designation']} | {s['face_id']} | Photo: {s['photo_path']}")
    print("=" * 60)

if __name__ == '__main__':
    main()
