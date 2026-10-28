import os
import cv2
import numpy as np
from datetime import datetime, date
from backend.config import STAFF_PHOTOS_DIR, UNKNOWN_SNAPSHOTS_DIR
from backend.database import init_db, add_staff, record_gate_event, add_saree_taka_record, add_inventory_event
from backend.face_engine import FaceRecognitionEngine

def generate_avatar(name: str, color: tuple, filename: str) -> str:
    """Generates a clean synthetic face/profile image for demo staff."""
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    img[:] = (25, 33, 44)  # Dark background
    
    # Head & Shoulders
    cv2.circle(img, (100, 75), 45, color, -1)
    cv2.circle(img, (100, 75), 45, (255, 255, 255), 2)
    # Eyes
    cv2.circle(img, (85, 70), 5, (20, 20, 20), -1)
    cv2.circle(img, (115, 70), 5, (20, 20, 20), -1)
    # Smile
    cv2.ellipse(img, (100, 88), (18, 10), 0, 0, 180, (20, 20, 20), 3)
    # Shoulders
    cv2.ellipse(img, (100, 180), (70, 45), 0, 0, 360, color, -1)
    
    filepath = STAFF_PHOTOS_DIR / filename
    cv2.imwrite(str(filepath), img)
    return str(filepath), f"/data/staff_photos/{filename}"

def seed():
    print("[Seed] Initializing Database...")
    init_db()
    face_engine = FaceRecognitionEngine()

    print("[Seed] Seeding Registered Textile Staff...")
    demo_staff = [
        {"name": "Ramesh Patel", "desig": "Master (Production Head)", "code": "TXS-001", "color": (210, 180, 140)},
        {"name": "Prakash Parmar", "desig": "Weaver (Rapier Machine)", "code": "TXS-002", "color": (190, 160, 130)},
        {"name": "Suresh Kumar", "desig": "Delivery Boy / Dispatcher", "code": "TXS-003", "color": (160, 190, 210)},
        {"name": "Meera Shah", "desig": "Office Staff / Accountant", "code": "TXS-004", "color": (220, 190, 180)},
        {"name": "Govind Vaghela", "desig": "Quality Checker (Folding)", "code": "TXS-005", "color": (180, 210, 190)}
    ]

    staff_ids = []
    for s in demo_staff:
        fname = f"demo_{s['code']}.jpg"
        abs_path, rel_path = generate_avatar(s["name"], s["color"], fname)
        img_bgr = cv2.imread(abs_path)
        
        # Compute face embedding
        emb = face_engine.compute_embedding(img_bgr)
        emb_list = emb.tolist() if emb is not None else None

        sid = add_staff(
            name=s["name"],
            designation=s["desig"],
            face_id=f"FC-{s['code']}",
            face_embedding=emb_list,
            photo_path=rel_path,
            staff_code=s["code"]
        )
        staff_ids.append(sid)
        print(f" -> Added staff: {s['name']} ({s['desig']}) [ID: {sid}]")

    print("[Seed] Seeding Today's Attendance Sessions...")
    # Simulate Ramesh entered at 08:30:15
    record_gate_event("Registered", "IN", staff_ids[0], confidence=0.96)
    # Simulate Prakash entered at 08:45:20
    record_gate_event("Registered", "IN", staff_ids[1], confidence=0.94)
    # Simulate Meera entered at 09:05:10
    record_gate_event("Registered", "IN", staff_ids[3], confidence=0.97)

    print("[Seed] Seeding Saree & Taka Delivery Challan Records (Module 2)...")
    add_saree_taka_record(
        challan_no="CH-2026-9041",
        party_name="Shri Ambica Weaving Mills",
        delivery_boy="Suresh Kumar",
        product_type="Raw Taka Bunch (20-40m)",
        expected_qty=10,
        counted_qty=10,
        signed_by="Ramesh Patel (Master)",
        notes="All 10 taka bunches checked and verified under camera"
    )

    add_saree_taka_record(
        challan_no="CH-2026-9042",
        party_name="Navkar Sarees Processors",
        delivery_boy="Mahesh Solanki",
        product_type="Finished Saree (Butta Cutting)",
        expected_qty=300,
        counted_qty=300,
        signed_by="Meera Shah",
        notes="Butta cut sarees matched exactly with challan"
    )

    print("[Seed] Seeding Inventory & Bimp Movements (Module 3)...")
    add_inventory_event("Yarn Carton Box", "IN", 15, "lock_batch_001", "Supplier: Reliance Polyester")
    add_inventory_event("Rapier Bimp (Beam)", "IN", 4, "lock_batch_002", "Weaving Section Rapier Line 2")

    print("[Seed] Successfully seeded all modules!")

if __name__ == "__main__":
    seed()
