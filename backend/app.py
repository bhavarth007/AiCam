import os
import cv2
import uuid
import base64
import numpy as np
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import (
    BASE_DIR, DATA_DIR, FRONTEND_DIR, STAFF_PHOTOS_DIR, 
    UNKNOWN_SNAPSHOTS_DIR, UPLOADED_VIDEOS_DIR, APP_NAME, VERSION
)
from backend.database import (
    init_db, add_staff, get_all_staff, get_staff_by_id, delete_staff, update_staff,
    get_today_attendance, get_unknown_visitors, get_attendance_summary_stats,
    add_saree_taka_record, get_saree_taka_records, clear_all_test_data,
    add_inventory_event, get_inventory_records, record_gate_event,
    delete_unknown_visitor, delete_all_unknown_visitors
)
from backend.face_engine import FaceRecognitionEngine
from backend.tracking_engine import GateTrackingEngine
from backend.video_streamer import VideoStreamManager

# Initialize Database Schema
init_db()

# Create FastAPI app
app = FastAPI(title=APP_NAME, version=VERSION)

# Enable CORS for local network and dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/" or request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Initialize AI Vision Subsystems
print("[App] Initializing Vision & Tracking Systems...")
face_engine = FaceRecognitionEngine()
tracking_engine = GateTrackingEngine(line_orientation="horizontal", line_pos_ratio=0.55)
stream_manager = VideoStreamManager(face_engine, tracking_engine)

# Auto-start stream with testing video (looped) as default; falls back to synthetic
stream_manager.start(source_type="file")

# Mount Static Files
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

# ----------------- Video & Stream Endpoints -----------------

@app.get("/api/video_feed")
def video_feed():
    """Live MJPEG video stream with real-time AI HUD."""
    return StreamingResponse(
        stream_manager.generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/camera/snapshot")
def get_camera_snapshot():
    """Captures a clean high-resolution snapshot directly from the active live AI camera feed."""
    jpeg_bytes = stream_manager.get_raw_snapshot_jpeg()
    if jpeg_bytes is None:
        raise HTTPException(status_code=503, detail="Camera frame not ready yet")
    return Response(content=jpeg_bytes, media_type="image/jpeg")

@app.get("/api/stats")
def get_stats(date_str: Optional[str] = None):
    """Returns real-time KPIs and system status."""
    today_stats = get_attendance_summary_stats(date_str)
    return {
        **today_stats,
        "fps": stream_manager.fps,
        "source_type": stream_manager.source_type,
        "source_path": stream_manager.source_path,
        "session_in": tracking_engine.count_in,
        "session_out": tracking_engine.count_out,
        "session_unknown": tracking_engine.count_unknown,
        "line_ratio": tracking_engine.line_pos_ratio,
        "line_orientation": tracking_engine.line_orientation,
        "is_counting": stream_manager.counting_active and not stream_manager.is_paused,
        "is_paused": stream_manager.is_paused,
    }

@app.get("/api/events/recent")
def get_recent_events():
    """Returns the latest gate crossing events for live feed."""
    return tracking_engine.recent_events

@app.post("/api/video/start_counting")
def start_counting():
    """Starts video playback and live line-crossing counting."""
    stream_manager.start_counting()
    return {"status": "success", "is_counting": True, "is_paused": False, "message": "Live counting and video started."}

@app.post("/api/video/stop_counting")
def stop_counting():
    """Pauses video playback and stops live line-crossing counting."""
    stream_manager.stop_counting()
    return {"status": "success", "is_counting": False, "is_paused": True, "message": "Live counting and video paused."}

@app.post("/api/video/toggle_counting")
def toggle_counting():
    """Toggles live counting between active and paused."""
    is_counting = stream_manager.toggle_counting()
    return {
        "status": "success",
        "is_counting": is_counting,
        "is_paused": not is_counting,
        "message": "Live counting active." if is_counting else "Live counting paused."
    }

@app.post("/api/video/reset_session")
def reset_session_counts():
    """Resets session gate crossings (IN/OUT/Unknown) to 0 and rewinds video."""
    stream_manager.reset_counts()
    return {"status": "success", "message": "Session counts reset to 0 and video rewound."}

@app.post("/api/video/set_source")
def set_video_source(source_type: str = Form(...), source_path: Optional[str] = Form(None)):
    """Switches active camera stream source (webcam, file, synthetic)."""
    stream_manager.start(source_type=source_type, source_path=source_path)
    return {"status": "success", "source_type": stream_manager.source_type, "source_path": stream_manager.source_path}

@app.post("/api/video/upload")
async def upload_gate_video(video: UploadFile = File(...)):
    """Uploads a user-provided gate CCTV recording (MP4/AVI/MKV) and immediately runs AI on it."""
    file_ext = Path(video.filename).suffix or ".mp4"
    saved_name = f"gate_footage_{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_ext}"
    saved_path = UPLOADED_VIDEOS_DIR / saved_name

    with open(saved_path, "wb") as f:
        content = await video.read()
        f.write(content)

    # Switch stream manager to use this uploaded video
    stream_manager.start(source_type="file", source_path=str(saved_path))
    return {
        "status": "success",
        "filename": saved_name,
        "path": str(saved_path),
        "message": "Gate video uploaded successfully and AI stream switched to file."
    }

@app.post("/api/tracking/set_line")
def set_gate_line(ratio: float = Form(...), orientation: Optional[str] = Form(None)):
    """Adjusts the position and orientation of the entrance gate line (legacy slider API)."""
    tracking_engine.set_line_position(ratio, orientation)
    return {
        "status": "success",
        "ratio": tracking_engine.line_pos_ratio,
        "orientation": tracking_engine.line_orientation,
        "x1": tracking_engine.line_x1_norm,
        "y1": tracking_engine.line_y1_norm,
        "x2": tracking_engine.line_x2_norm,
        "y2": tracking_engine.line_y2_norm,
    }

@app.post("/api/tracking/set_line_coords")
def set_gate_line_coords(
    x1: float = Form(...),
    y1: float = Form(...),
    x2: float = Form(...),
    y2: float = Form(...)
):
    """
    Sets the gate line by two arbitrary normalized endpoints (0.0-1.0).
    Supports any angle, any position, and variable length on the live frame.
    Called by the frontend canvas drag interaction.
    """
    tracking_engine.set_line_coords(x1, y1, x2, y2)
    return {
        "status": "success",
        "x1": tracking_engine.line_x1_norm,
        "y1": tracking_engine.line_y1_norm,
        "x2": tracking_engine.line_x2_norm,
        "y2": tracking_engine.line_y2_norm,
    }

@app.get("/api/tracking/get_line")
def get_gate_line():
    """Returns the current gate line normalized endpoint coordinates."""
    return {
        "x1": tracking_engine.line_x1_norm,
        "y1": tracking_engine.line_y1_norm,
        "x2": tracking_engine.line_x2_norm,
        "y2": tracking_engine.line_y2_norm,
        "orientation": tracking_engine.line_orientation,
        "ratio": tracking_engine.line_pos_ratio,
    }

# ----------------- Staff Registration & Face ID Endpoints -----------------

@app.post("/api/staff/register")
async def register_staff(
    name: str = Form(...),
    designation: str = Form(...),
    face_id: str = Form(...),
    photo: Optional[UploadFile] = File(None),
    photo_base64: Optional[str] = Form(None),
    photo_url: Optional[str] = Form(None)
):
    """
    Registers a new staff/worker with Name, Designation, and Face ID photo.
    Supports file upload, webcam base64, live AI camera snapshot, or unknown visitor photo.
    """
    img_bgr = None
    saved_rel_path = ""
    clean_fid = "".join(c for c in face_id if c.isalnum() or c in "-_")

    # 1. Process uploaded photo file
    if photo and photo.filename:
        content = await photo.read()
        nparr = np.frombuffer(content, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        file_ext = Path(photo.filename).suffix or ".jpg"
        filename = f"staff_{clean_fid}_{uuid.uuid4().hex[:6]}{file_ext}"
        filepath = STAFF_PHOTOS_DIR / filename
        with open(filepath, "wb") as f:
            f.write(content)
        saved_rel_path = f"/data/staff_photos/{filename}"

    # 2. Or process photo from unknown snapshot URL
    elif photo_url and photo_url.strip():
        url_str = photo_url.strip()
        if "/data/" in url_str:
            rel = url_str.split("/data/")[1]
            source_path = DATA_DIR / rel
        else:
            source_path = BASE_DIR / url_str.lstrip("/")

        if source_path.exists():
            img_bgr = cv2.imread(str(source_path))
            filename = f"staff_{clean_fid}_{uuid.uuid4().hex[:6]}.jpg"
            target_path = STAFF_PHOTOS_DIR / filename
            cv2.imwrite(str(target_path), img_bgr)
            saved_rel_path = f"/data/staff_photos/{filename}"
        else:
            raise HTTPException(status_code=400, detail=f"Source snapshot file not found: {url_str}")

    # 3. Or process base64 photo captured via webcam / live camera
    elif photo_base64 and photo_base64.strip():
        try:
            b64_str = photo_base64.strip()
            if "," in b64_str:
                b64_str = b64_str.split(",")[1]
            img_bytes = base64.b64decode(b64_str)
            nparr = np.frombuffer(img_bytes, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            filename = f"staff_{clean_fid}_{uuid.uuid4().hex[:6]}.jpg"
            filepath = STAFF_PHOTOS_DIR / filename
            cv2.imwrite(str(filepath), img_bgr)
            saved_rel_path = f"/data/staff_photos/{filename}"
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 image: {e}")

    if img_bgr is None:
        raise HTTPException(status_code=400, detail="Photo is required for Face ID registration.")

    # 4. Extract Face Embedding
    success, emb, face_crop, msg = face_engine.register_staff_face(img_bgr)
    if not success or emb is None:
        raise HTTPException(status_code=400, detail=msg)

    # 5. Save to Database
    try:
        staff_id = add_staff(
            name=name.strip(),
            designation=designation.strip(),
            face_id=face_id.strip(),
            face_embedding=emb,
            photo_path=saved_rel_path
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Database registration failed: {e}")

    # 6. Reload cached face embeddings
    face_engine.reload_registered_staff()

    return {
        "status": "success",
        "staff_id": staff_id,
        "name": name,
        "designation": designation,
        "face_id": face_id,
        "photo_path": saved_rel_path,
        "message": f"Staff member {name} ({designation}) registered successfully."
    }

@app.post("/api/staff/update")
def edit_staff(staff_id: int = Form(...), name: str = Form(...), designation: str = Form(...)):
    """Edits an existing staff member's name and designation."""
    update_staff(staff_id, name, designation)
    face_engine.reload_registered_staff()
    return {"status": "success", "message": f"Updated staff details for {name}"}

@app.get("/api/staff")
def list_staff():
    """Lists all active registered staff members."""
    return get_all_staff()

@app.delete("/api/staff/{staff_id}")
def remove_staff(staff_id: int):
    """Deactivates a staff member."""
    success = delete_staff(staff_id)
    face_engine.reload_registered_staff()
    return {"status": "success", "message": f"Staff ID {staff_id} deactivated."}

@app.post("/api/system/clear_data")
def clear_system_data(clear_staff: bool = Form(False)):
    """Cleans all test/raw data from attendance logs, unknown visitors, and inventory."""
    clear_all_test_data(clear_staff=clear_staff)
    tracking_engine.recent_events.clear()
    tracking_engine.count_in = 0
    tracking_engine.count_out = 0
    tracking_engine.count_unknown = 0
    face_engine.reload_registered_staff()
    return {"status": "success", "message": "All raw/test attendance data has been successfully cleaned."}

# ----------------- Attendance Reports Endpoints -----------------

@app.get("/api/attendance/today")
def get_today_report():
    """Returns today's detailed attendance log with in/out times and calculated working hours."""
    records = get_today_attendance()
    return {
        "date": date.today().strftime("%Y-%m-%d"),
        "total_records": len(records),
        "records": records
    }

@app.get("/api/attendance/report")
def get_custom_report(date_str: Optional[str] = Query(None, alias="date")):
    """Returns attendance for a specific date (YYYY-MM-DD)."""
    target_date = date_str or date.today().strftime("%Y-%m-%d")
    records = get_today_attendance(target_date)
    stats = get_attendance_summary_stats(target_date)
    return {
        "date": target_date,
        "stats": stats,
        "records": records
    }

@app.get("/api/unknowns")
def list_unknowns(date_str: Optional[str] = Query(None, alias="date")):
    """Returns photos and timestamps of unregistered/unknown visitors captured by AI camera."""
    return get_unknown_visitors(date_str)

@app.delete("/api/unknowns/{visitor_id}")
def remove_unknown_visitor(visitor_id: int):
    """Deletes an unknown visitor record and its snapshot image."""
    delete_unknown_visitor(visitor_id)
    return {"status": "success", "message": f"Unknown visitor {visitor_id} deleted."}

@app.delete("/api/unknowns")
def remove_all_unknowns(date_str: Optional[str] = Query(None, alias="date")):
    """Deletes all unknown visitors for a specific date or all dates."""
    clean_date = date_str.strip() if (date_str and date_str.strip()) else None
    count = delete_all_unknown_visitors(clean_date)
    tracking_engine.count_unknown = 0
    tracking_engine.recent_events = [e for e in tracking_engine.recent_events if e.get("type") != "unknown"]
    return {"status": "success", "count": count, "message": f"Successfully deleted {count} unknown visitor snapshot(s)."}

@app.post("/api/unknowns/clear_all")
def clear_all_unknowns_post(date_str: Optional[str] = Form(None)):
    """Alternate POST endpoint to delete unknown visitors ensuring 100% browser compatibility."""
    clean_date = date_str.strip() if (date_str and date_str.strip()) else None
    count = delete_all_unknown_visitors(clean_date)
    tracking_engine.count_unknown = 0
    tracking_engine.recent_events = [e for e in tracking_engine.recent_events if e.get("type") != "unknown"]
    return {"status": "success", "count": count, "message": f"Successfully deleted {count} unknown visitor snapshot(s)."}

@app.post("/api/attendance/manual_event")
def manual_gate_event(staff_id: int = Form(...), direction: str = Form(...)):
    """Allows manual entry/exit simulation or security desk override."""
    record_gate_event(
        person_type="Registered",
        direction=direction.upper(),
        staff_id=staff_id,
        confidence=1.0,
        snapshot_path=None
    )
    return {"status": "success", "message": f"Manual {direction.upper()} recorded for staff ID {staff_id}."}

# ----------------- Module 2: Sarees & Taka Challan Matching Endpoints -----------------

class SareeTakaRecordRequest(BaseModel):
    challan_no: str
    party_name: str
    delivery_boy: str
    product_type: str
    expected_qty: int
    counted_qty: int
    signed_by: Optional[str] = None
    notes: Optional[str] = ""

@app.post("/api/module2/record")
def create_saree_taka_record(req: SareeTakaRecordRequest):
    """Logs count of taka bunches (20-40m rolls) or finished sarees matched against delivery challan."""
    rec_id = add_saree_taka_record(
        challan_no=req.challan_no,
        party_name=req.party_name,
        delivery_boy=req.delivery_boy,
        product_type=req.product_type,
        expected_qty=req.expected_qty,
        counted_qty=req.counted_qty,
        signed_by=req.signed_by,
        notes=req.notes or ""
    )
    return {"status": "success", "record_id": rec_id, "message": "Saree/Taka counting record stored."}

@app.get("/api/module2/records")
def list_saree_taka_records(date_str: Optional[str] = Query(None, alias="date")):
    """Lists all saree and taka challan verification records."""
    return get_saree_taka_records(date_str)

# ----------------- Module 3: Inventory (Boxes, Bimps, Zari) Endpoints -----------------

class InventoryRecordRequest(BaseModel):
    material_type: str
    direction: str
    batch_count: int = 1
    lock_token: Optional[str] = None
    notes: Optional[str] = ""

@app.post("/api/module3/record")
def create_inventory_record(req: InventoryRecordRequest):
    """Counts yarn boxes, rapier machine bimps (beams), and materials with anti-double-count lock."""
    token = req.lock_token or f"lock_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    success = add_inventory_event(
        material_type=req.material_type,
        direction=req.direction.upper(),
        batch_count=req.batch_count,
        lock_token=token,
        notes=req.notes or ""
    )
    if not success:
        return {"status": "blocked", "message": "Duplicate count blocked by Anti-Double-Count Lock System."}
    return {"status": "success", "lock_token": token, "message": "Inventory material count logged successfully."}

@app.get("/api/module3/records")
def list_inventory_records(date_str: Optional[str] = Query(None, alias="date")):
    """Lists inventory movements (yarn boxes, rapier bimps)."""
    return get_inventory_records(date_str)

# ----------------- Serve Frontend Single-Page App -----------------

@app.get("/")
def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend index.html is being prepared."}
