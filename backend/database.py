import sqlite3
import json
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from backend.config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Staff and Workers Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_code TEXT UNIQUE,
        name TEXT NOT NULL,
        designation TEXT NOT NULL,
        face_id TEXT UNIQUE NOT NULL,
        face_embedding TEXT,  -- JSON serialized list of floats
        photo_path TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT NOT NULL
    )
    """)

    # 2. Daily Attendance Records (Tracks in_time, out_time, total_hours, in_count, out_count)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        in_time TEXT NOT NULL,
        out_time TEXT,
        total_hours REAL DEFAULT 0.0,
        in_count INTEGER DEFAULT 1,
        out_count INTEGER DEFAULT 0,
        total_outside_hours REAL DEFAULT 0.0,
        last_in_timestamp TEXT,
        last_out_timestamp TEXT,
        status TEXT DEFAULT 'Working',
        last_seen TEXT NOT NULL,
        notes TEXT,
        FOREIGN KEY (staff_id) REFERENCES staff (id),
        UNIQUE(staff_id, date)
    )
    """)

    # Check and add columns if upgrading existing DB
    cursor.execute("PRAGMA table_info(attendance_logs)")
    cols = [c[1] for c in cursor.fetchall()]
    if "in_count" not in cols:
        cursor.execute("ALTER TABLE attendance_logs ADD COLUMN in_count INTEGER DEFAULT 1")
    if "out_count" not in cols:
        cursor.execute("ALTER TABLE attendance_logs ADD COLUMN out_count INTEGER DEFAULT 0")
    if "total_outside_hours" not in cols:
        cursor.execute("ALTER TABLE attendance_logs ADD COLUMN total_outside_hours REAL DEFAULT 0.0")
    if "last_in_timestamp" not in cols:
        cursor.execute("ALTER TABLE attendance_logs ADD COLUMN last_in_timestamp TEXT")
    if "last_out_timestamp" not in cols:
        cursor.execute("ALTER TABLE attendance_logs ADD COLUMN last_out_timestamp TEXT")

    # 3. Raw Line Crossing Event Logs (Each IN or OUT gate passage)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gate_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_type TEXT NOT NULL,       -- 'Registered' or 'Unknown'
        staff_id INTEGER,
        direction TEXT NOT NULL,         -- 'IN' or 'OUT'
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        snapshot_path TEXT,
        FOREIGN KEY (staff_id) REFERENCES staff (id)
    )
    """)

    # 4. Unknown Persons Log (Captures photo when unregistered face is seen)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS unknown_visitors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        snapshot_path TEXT NOT NULL,
        camera_id TEXT DEFAULT 'Gate Cam 1',
        status TEXT DEFAULT 'Unreviewed', -- Unreviewed, Approved, Flagged
        notes TEXT
    )
    """)

    # 5. Module 2: Sarees & Taka Counting Records (Taka rolls 20-40m bunches, Finished Sarees vs Challan)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saree_taka_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        challan_no TEXT,
        party_name TEXT,
        delivery_boy TEXT,
        product_type TEXT NOT NULL,       -- 'Taka Bunch (20-40m)', 'Finished Sarees', 'Butta Cut Saree', 'Mill Saree'
        expected_qty INTEGER DEFAULT 0,
        counted_qty INTEGER DEFAULT 0,
        difference INTEGER DEFAULT 0,
        status TEXT DEFAULT 'Pending',    -- 'Matched & Signed', 'Discrepancy', 'Pending Sign'
        signed_by TEXT,
        notes TEXT
    )
    """)

    # 6. Module 3: Yarn Boxes, Bimps (Rapier machine beams) & Materials
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventory_material_counts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        material_type TEXT NOT NULL,     -- 'Yarn Box', 'Rapier Bimp (Beam)', 'Zari Spool Box', 'Other Product'
        direction TEXT NOT NULL,         -- 'IN', 'OUT'
        batch_count INTEGER DEFAULT 1,
        lock_token TEXT UNIQUE,          -- Prevents double count within cooldown
        camera_id TEXT DEFAULT 'Gate Cam 1',
        notes TEXT
    )
    """)

    # 7. Universal Camera Registry
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cameras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        brand TEXT NOT NULL,
        connection_type TEXT NOT NULL,
        ip_address TEXT,
        port INTEGER DEFAULT 554,
        username TEXT,
        password_enc TEXT,
        channel INTEGER DEFAULT 1,
        rtsp_path TEXT,
        stream_quality TEXT DEFAULT 'sub',
        main_rtsp_url TEXT,
        sub_rtsp_url TEXT,
        status TEXT DEFAULT 'disconnected',
        fps REAL DEFAULT 0.0,
        latency_ms REAL DEFAULT 0.0,
        last_error TEXT,
        last_seen TEXT,
        is_active INTEGER DEFAULT 1,
        assigned_module TEXT DEFAULT 'attendance',
        geometry_config TEXT,
        tenant_id TEXT DEFAULT 'default',
        created_at TEXT NOT NULL
    )
    """)

    # 8. Staff Reference Photos (Multi-Angle Biometric Enrollment)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staff_reference_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        pose_type TEXT NOT NULL,
        photo_path TEXT NOT NULL,
        face_embedding TEXT,
        quality_score REAL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (staff_id) REFERENCES staff (id) ON DELETE CASCADE
    )
    """)

    # 9. Product Categories & Detection Classes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        yolo_class_id INTEGER,
        yolo_class_name TEXT,
        color_hex TEXT DEFAULT '#06b6d4',
        tenant_id TEXT DEFAULT 'default',
        created_at TEXT NOT NULL
    )
    """)

    # 10. Product Counting Live Events
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_counting_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id TEXT NOT NULL,
        product_category TEXT NOT NULL,
        direction TEXT NOT NULL,
        track_id INTEGER,
        confidence REAL DEFAULT 0.0,
        quantity INTEGER DEFAULT 1,
        shift_name TEXT DEFAULT 'General',
        timestamp TEXT NOT NULL,
        date TEXT NOT NULL,
        snapshot_path TEXT,
        tenant_id TEXT DEFAULT 'default'
    )
    """)

    # 11. Commercial Tenants & Module Licensing
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tenants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT UNIQUE NOT NULL,
        company_name TEXT NOT NULL,
        contact_email TEXT,
        attendance_enabled INTEGER DEFAULT 1,
        counting_enabled INTEGER DEFAULT 1,
        max_cameras INTEGER DEFAULT 8,
        api_key TEXT UNIQUE,
        created_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


# ----------------- Staff Functions -----------------

def add_staff(name: str, designation: str, face_id: str, face_embedding: Optional[List[float]], photo_path: str, staff_code: Optional[str] = None) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if not staff_code:
        # Generate staff code
        cursor.execute("SELECT COUNT(*) FROM staff")
        count = cursor.fetchone()[0] + 1
        staff_code = f"TXS-{count:03d}"
        
    emb_json = json.dumps(face_embedding) if face_embedding is not None else None
    
    cursor.execute("""
        INSERT INTO staff (staff_code, name, designation, face_id, face_embedding, photo_path, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
    """, (staff_code, name, designation, face_id, emb_json, photo_path, now_str))
    
    staff_id = cursor.lastrowid
    return staff_id

def get_all_staff() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, staff_code, name, designation, face_id, photo_path, status, created_at FROM staff WHERE status = 'active' ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_staff_with_embeddings() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, staff_code, name, designation, face_id, face_embedding, photo_path FROM staff WHERE status = 'active'")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        d = dict(r)
        if d.get("face_embedding"):
            try:
                d["face_embedding"] = json.loads(d["face_embedding"])
            except Exception:
                d["face_embedding"] = None
        results.append(d)
    return results

def get_staff_by_id(staff_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        if d.get("face_embedding"):
            try:
                d["face_embedding"] = json.loads(d["face_embedding"])
            except Exception:
                d["face_embedding"] = None
        return d
    return None

def delete_staff(staff_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE staff SET status = 'deleted' WHERE id = ?", (staff_id,))
    return True

def update_staff(staff_id: int, name: str, designation: str, face_id: Optional[str] = None, face_embedding: Optional[List[float]] = None, photo_path: Optional[str] = None) -> bool:
    """Updates staff details, including optional embedding and photo."""
    conn = get_connection()
    cursor = conn.cursor()
    updates = ["name = ?", "designation = ?"]
    params = [name.strip(), designation.strip()]

    if face_id is not None:
        updates.append("face_id = ?")
        params.append(face_id.strip())
    if face_embedding is not None:
        updates.append("face_embedding = ?")
        params.append(json.dumps(face_embedding))
    if photo_path is not None:
        updates.append("photo_path = ?")
        params.append(photo_path.strip())

    params.append(staff_id)
    query = f"UPDATE staff SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, tuple(params))
    return True

# ----------------- Attendance Logging Functions -----------------

def record_gate_event(person_type: str, direction: str, staff_id: Optional[int] = None, confidence: float = 0.0, snapshot_path: Optional[str] = None):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    cursor.execute("""
        INSERT INTO gate_events (person_type, staff_id, direction, timestamp, date, confidence, snapshot_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (person_type, staff_id, direction, now_str, today_str, confidence, snapshot_path))
    
    # If registered staff
    if staff_id and person_type == "Registered":
        # Check if record exists for today
        cursor.execute("SELECT * FROM attendance_logs WHERE staff_id = ? AND date = ?", (staff_id, today_str))
        existing = cursor.fetchone()
        
        if direction == "IN":
            if not existing:
                # First IN of the day -> Start working time
                cursor.execute("""
                    INSERT INTO attendance_logs (staff_id, date, in_time, out_time, total_hours, in_count, out_count, total_outside_hours, last_in_timestamp, last_out_timestamp, status, last_seen)
                    VALUES (?, ?, ?, NULL, 0.0, 1, 0, 0.0, ?, NULL, 'Working', ?)
                """, (staff_id, today_str, time_str, now_str, now_str))
            else:
                ex_d = dict(existing)
                new_in_count = (ex_d.get("in_count") or 1)
                new_outside_hrs = (ex_d.get("total_outside_hours") or 0.0)

                # If they were previously Outside, calculate time spent outside on this trip
                if ex_d.get("last_out_timestamp") and ex_d.get("status") == "Outside":
                    try:
                        out_dt = datetime.strptime(ex_d["last_out_timestamp"], "%Y-%m-%d %H:%M:%S")
                        out_sec = (now - out_dt).total_seconds()
                        new_outside_hrs += max(0.0, round(out_sec / 3600.0, 2))
                    except Exception:
                        pass
                    new_in_count += 1

                cursor.execute("""
                    UPDATE attendance_logs 
                    SET out_time = NULL, in_count = ?, total_outside_hours = ?, last_in_timestamp = ?, last_seen = ?, status = 'Working'
                    WHERE id = ?
                """, (new_in_count, new_outside_hrs, now_str, now_str, ex_d["id"]))
                
        elif direction == "OUT":
            if existing:
                ex_d = dict(existing)
                new_out_count = (ex_d.get("out_count") or 0) + 1
                cur_work_hrs = (ex_d.get("total_hours") or 0.0)

                # Calculate time spent inside during this shift segment
                last_in_str = ex_d.get("last_in_timestamp") or f"{today_str} {ex_d['in_time']}"
                try:
                    last_in_dt = datetime.strptime(last_in_str, "%Y-%m-%d %H:%M:%S")
                    in_sec = (now - last_in_dt).total_seconds()
                    cur_work_hrs += max(0.0, round(in_sec / 3600.0, 2))
                except Exception:
                    pass

                cursor.execute("""
                    UPDATE attendance_logs 
                    SET out_time = ?, out_count = ?, total_hours = ?, last_out_timestamp = ?, status = 'Outside', last_seen = ?
                    WHERE id = ?
                """, (time_str, new_out_count, cur_work_hrs, now_str, now_str, ex_d["id"]))
            else:
                # Recorded an OUT without initial IN
                cursor.execute("""
                    INSERT INTO attendance_logs (staff_id, date, in_time, out_time, total_hours, in_count, out_count, total_outside_hours, last_in_timestamp, last_out_timestamp, status, last_seen, notes)
                    VALUES (?, ?, ?, ?, 0.0, 0, 1, 0.0, NULL, ?, 'Outside', ?, 'Exited through gate')
                """, (staff_id, today_str, time_str, time_str, now_str, now_str))


def log_unknown_visitor(snapshot_path: str, camera_id: str = "Gate Cam 1", notes: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")
    
    cursor.execute("""
        INSERT INTO unknown_visitors (timestamp, date, snapshot_path, camera_id, status, notes)
        VALUES (?, ?, ?, ?, 'Unreviewed', ?)
    """, (now_str, today_str, snapshot_path, camera_id, notes))
    
    record_id = cursor.lastrowid
    
    # Also log as gate event
    cursor.execute("""
        INSERT INTO gate_events (person_type, staff_id, direction, timestamp, date, confidence, snapshot_path)
        VALUES ('Unknown', NULL, 'IN', ?, ?, 0.0, ?)
    """, (now_str, today_str, snapshot_path))
    
    return record_id

def delete_unknown_visitor(visitor_id: int) -> bool:
    """Deletes an unknown visitor record and its snapshot image from disk."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT snapshot_path FROM unknown_visitors WHERE id = ?", (visitor_id,))
    row = cursor.fetchone()
    if row and row["snapshot_path"]:
        snap_path = row["snapshot_path"]
        from backend.config import DATA_DIR
        if "/data/" in snap_path:
            rel = snap_path.split("/data/")[1]
            fpath = DATA_DIR / rel
            if fpath.exists():
                try:
                    fpath.unlink()
                except Exception:
                    pass
    cursor.execute("DELETE FROM unknown_visitors WHERE id = ?", (visitor_id,))
    return True

def delete_all_unknown_visitors(date_str: Optional[str] = None) -> int:
    """Deletes all unknown visitors (optionally by date) and their snapshots from disk."""
    conn = get_connection()
    cursor = conn.cursor()
    from backend.config import DATA_DIR, UNKNOWN_SNAPSHOTS_DIR
    import shutil

    count = 0
    clean_date = date_str.strip() if (date_str and date_str.strip()) else None

    if clean_date:
        cursor.execute("SELECT id, snapshot_path FROM unknown_visitors WHERE date = ?", (clean_date,))
        rows = cursor.fetchall()
        count = len(rows)
        for row in rows:
            snap_path = row["snapshot_path"]
            if snap_path and "/data/" in snap_path:
                rel = snap_path.split("/data/")[1]
                fpath = DATA_DIR / rel
                if fpath.exists():
                    try:
                        fpath.unlink()
                    except Exception:
                        pass
        # Remove date subfolder if empty or remaining
        date_folder = UNKNOWN_SNAPSHOTS_DIR / clean_date
        if date_folder.exists() and date_folder.is_dir():
            try:
                shutil.rmtree(date_folder, ignore_errors=True)
            except Exception:
                pass

        cursor.execute("DELETE FROM unknown_visitors WHERE date = ?", (clean_date,))
        cursor.execute("DELETE FROM gate_events WHERE person_type = 'Unknown' AND date = ?", (clean_date,))
    else:
        cursor.execute("SELECT id, snapshot_path FROM unknown_visitors")
        rows = cursor.fetchall()
        count = len(rows)
        for row in rows:
            snap_path = row["snapshot_path"]
            if snap_path and "/data/" in snap_path:
                rel = snap_path.split("/data/")[1]
                fpath = DATA_DIR / rel
                if fpath.exists():
                    try:
                        fpath.unlink()
                    except Exception:
                        pass
        # Clean all items inside UNKNOWN_SNAPSHOTS_DIR
        if UNKNOWN_SNAPSHOTS_DIR.exists():
            for item in UNKNOWN_SNAPSHOTS_DIR.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink()
                except Exception:
                    pass

        cursor.execute("DELETE FROM unknown_visitors")
        cursor.execute("DELETE FROM gate_events WHERE person_type = 'Unknown'")

    return count

def get_today_attendance(date_str: Optional[str] = None) -> List[Dict[str, Any]]:
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT a.id, a.staff_id, s.staff_code, s.name, s.designation, s.photo_path,
               a.date, a.in_time, a.out_time, a.total_hours, a.in_count, a.out_count,
               a.total_outside_hours, a.last_in_timestamp, a.last_out_timestamp,
               a.status, a.last_seen, a.notes
        FROM attendance_logs a
        JOIN staff s ON a.staff_id = s.id
        WHERE a.date = ?
        ORDER BY a.in_time DESC
    """, (date_str,))
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    now = datetime.now()
    for row in rows:
        d = dict(row)
        total_work = d.get("total_hours") or 0.0
        total_out = d.get("total_outside_hours") or 0.0
        in_cnt = d.get("in_count") or 1
        out_cnt = d.get("out_count") or 0

        # If currently "Working", calculate live ongoing hours for this current segment
        if d["status"] == "Working":
            last_in_str = d.get("last_in_timestamp") or f"{d['date']} {d['in_time']}"
            try:
                in_dt = datetime.strptime(last_in_str, "%Y-%m-%d %H:%M:%S")
                segment_hrs = max(0.0, (now - in_dt).total_seconds() / 3600.0)
                d["live_hours"] = round(total_work + segment_hrs, 2)
            except Exception:
                d["live_hours"] = round(total_work, 2)
            d["hours_outside"] = round(total_out, 2)
        else:
            # Currently "Outside"
            d["live_hours"] = round(total_work, 2)
            last_out_str = d.get("last_out_timestamp") or (f"{d['date']} {d['out_time']}" if d.get("out_time") else None)
            if last_out_str:
                try:
                    out_dt = datetime.strptime(last_out_str, "%Y-%m-%d %H:%M:%S")
                    cur_out_sec = max(0.0, (now - out_dt).total_seconds())
                    d["hours_outside"] = round(total_out + (cur_out_sec / 3600.0), 2)
                except Exception:
                    d["hours_outside"] = round(total_out, 2)
            else:
                d["hours_outside"] = round(total_out, 2)

        d["in_count"] = in_cnt
        d["out_count"] = out_cnt
        results.append(d)
        
    return results

def get_unknown_visitors(date_str: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if date_str:
        cursor.execute("SELECT * FROM unknown_visitors WHERE date = ? ORDER BY id DESC", (date_str,))
    else:
        cursor.execute("SELECT * FROM unknown_visitors ORDER BY id DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in rows:
        d = dict(row)
        notes = d.get("notes") or ""
        if "full:" in notes:
            d["full_path"] = notes.split("full:")[1].strip()
        else:
            d["full_path"] = d.get("snapshot_path")
        results.append(d)
    return results

def get_attendance_summary_stats(date_str: Optional[str] = None) -> Dict[str, Any]:
    if not date_str:
        date_str = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    
    # Total registered staff
    cursor.execute("SELECT COUNT(*) FROM staff WHERE status = 'active'")
    total_staff = cursor.fetchone()[0]
    
    # Today present
    cursor.execute("SELECT COUNT(*) FROM attendance_logs WHERE date = ?", (date_str,))
    present_today = cursor.fetchone()[0]
    
    # Currently inside (Working)
    cursor.execute("SELECT COUNT(*) FROM attendance_logs WHERE date = ? AND status = 'Working'", (date_str,))
    currently_inside = cursor.fetchone()[0]
    
    # Total unknowns today
    cursor.execute("SELECT COUNT(*) FROM unknown_visitors WHERE date = ?", (date_str,))
    unknowns_today = cursor.fetchone()[0]
    
    conn.close()
    
    absent = max(0, total_staff - present_today)
    return {
        "date": date_str,
        "total_staff": total_staff,
        "present_today": present_today,
        "currently_inside": currently_inside,
        "absent_today": absent,
        "unknowns_today": unknowns_today
    }

# ----------------- Module 2: Sarees & Taka Records -----------------

def add_saree_taka_record(challan_no: str, party_name: str, delivery_boy: str, product_type: str, expected_qty: int, counted_qty: int, signed_by: Optional[str] = None, notes: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")
    diff = counted_qty - expected_qty
    
    status = "Pending Sign"
    if signed_by:
        status = "Matched & Signed" if diff == 0 else "Discrepancy Signed"
    elif diff != 0:
        status = "Discrepancy"
        
    cursor.execute("""
        INSERT INTO saree_taka_records (timestamp, date, challan_no, party_name, delivery_boy, product_type, expected_qty, counted_qty, difference, status, signed_by, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (now_str, today_str, challan_no, party_name, delivery_boy, product_type, expected_qty, counted_qty, diff, status, signed_by, notes))
    
    rec_id = cursor.lastrowid
    return rec_id

def get_saree_taka_records(date_str: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if date_str:
        cursor.execute("SELECT * FROM saree_taka_records WHERE date = ? ORDER BY id DESC", (date_str,))
    else:
        cursor.execute("SELECT * FROM saree_taka_records ORDER BY id DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------- Module 3: Inventory (Boxes, Bimps, Zari) -----------------

def add_inventory_event(material_type: str, direction: str, batch_count: int, lock_token: str, notes: str = "") -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    today_str = now.strftime("%Y-%m-%d")
    
    try:
        cursor.execute("""
            INSERT INTO inventory_material_counts (timestamp, date, material_type, direction, batch_count, lock_token, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (now_str, today_str, material_type, direction, batch_count, lock_token, notes))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        # Lock token already exists -> prevented double counting!
        success = False
    finally:
        conn.close()
    return success

def get_inventory_records(date_str: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    if date_str:
        cursor.execute("SELECT * FROM inventory_material_counts WHERE date = ? ORDER BY id DESC", (date_str,))
    else:
        cursor.execute("SELECT * FROM inventory_material_counts ORDER BY id DESC LIMIT 100")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------- System Data Cleanup -----------------

def clear_all_test_data(clear_staff: bool = False):
    """Clears all raw/dummy attendance logs, events, unknown visitors, and inventory records."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM attendance_logs")
    cursor.execute("DELETE FROM gate_events")
    cursor.execute("DELETE FROM unknown_visitors")
    cursor.execute("DELETE FROM saree_taka_records")
    cursor.execute("DELETE FROM inventory_material_counts")
    if clear_staff:
        cursor.execute("DELETE FROM staff")
    else:
        # Delete demo seed staff TXS-001 through TXS-005
        cursor.execute("DELETE FROM staff WHERE staff_code LIKE 'TXS-00%'")
    return True


# ----------------- Commercial Platform: Camera Registry -----------------

def add_camera(data: Dict[str, Any]) -> str:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Generate camera_id if not present
    camera_id = data.get("camera_id")
    if not camera_id:
        cursor.execute("SELECT COUNT(*) FROM cameras")
        count = cursor.fetchone()[0] + 1
        camera_id = f"cam_{count:02d}"

    cursor.execute("""
        INSERT INTO cameras (
            camera_id, name, brand, connection_type, ip_address, port, username, password_enc,
            channel, rtsp_path, stream_quality, main_rtsp_url, sub_rtsp_url, status,
            is_active, assigned_module, geometry_config, tenant_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'disconnected', 1, ?, ?, ?, ?)
    """, (
        camera_id,
        data.get("name") or f"Camera {camera_id}",
        data.get("brand", "generic_rtsp"),
        data.get("connection_type", "rtsp"),
        data.get("ip_address", "127.0.0.1"),
        int(data.get("port") or 554),
        data.get("username", "admin"),
        data.get("password", ""),
        int(data.get("channel") or 1),
        data.get("rtsp_path", ""),
        data.get("stream_quality", "sub"),
        data.get("main_rtsp_url", ""),
        data.get("sub_rtsp_url", ""),
        data.get("assigned_module", "attendance"),
        data.get("geometry_config", "{}"),
        data.get("tenant_id", "default"),
        now_str
    ))
    conn.commit()
    conn.close()
    return camera_id

def get_all_cameras(tenant_id: str = "default") -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, camera_id, name, brand, connection_type, ip_address, port,
               username, channel, rtsp_path, stream_quality, main_rtsp_url, sub_rtsp_url,
               status, fps, latency_ms, last_error, last_seen, is_active, assigned_module,
               geometry_config, tenant_id, created_at
        FROM cameras WHERE is_active = 1 AND tenant_id = ? ORDER BY id ASC
    """, (tenant_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_camera_by_id(camera_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cameras WHERE camera_id = ?", (camera_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_camera(camera_id: str, updates: Dict[str, Any]) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    fields = []
    params = []
    for k, v in updates.items():
        if k in ("name", "brand", "connection_type", "ip_address", "port", "username",
                 "password_enc", "channel", "rtsp_path", "stream_quality", "main_rtsp_url",
                 "sub_rtsp_url", "status", "assigned_module", "geometry_config", "is_active"):
            fields.append(f"{k} = ?")
            params.append(v)
    if not fields:
        conn.close()
        return False
    params.append(camera_id)
    cursor.execute(f"UPDATE cameras SET {', '.join(fields)} WHERE camera_id = ?", tuple(params))
    conn.commit()
    conn.close()
    return True

def delete_camera(camera_id: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE cameras SET is_active = 0 WHERE camera_id = ?", (camera_id,))
    conn.commit()
    conn.close()
    return True

def update_camera_status(camera_id: str, status: str, fps: float, latency_ms: float, last_error: str = ""):
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        UPDATE cameras
        SET status = ?, fps = ?, latency_ms = ?, last_error = ?, last_seen = ?
        WHERE camera_id = ?
    """, (status, round(fps, 1), round(latency_ms, 1), last_error, now_str, camera_id))
    conn.commit()
    conn.close()

# ----------------- Multi-Angle Staff Reference Photos -----------------

def add_staff_reference_photo(staff_id: int, pose_type: str, photo_path: str, face_embedding: Optional[List[float]], quality_score: float = 1.0) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    emb_json = json.dumps(face_embedding) if face_embedding is not None else None
    cursor.execute("""
        INSERT INTO staff_reference_photos (staff_id, pose_type, photo_path, face_embedding, quality_score, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (staff_id, pose_type, photo_path, emb_json, quality_score, now_str))
    photo_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return photo_id

def get_staff_reference_photos(staff_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, staff_id, pose_type, photo_path, quality_score, created_at
        FROM staff_reference_photos WHERE staff_id = ? ORDER BY id ASC
    """, (staff_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_staff_reference_photo(photo_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM staff_reference_photos WHERE id = ?", (photo_id,))
    conn.commit()
    conn.close()
    return True

# ----------------- Product Counting & Category Operations -----------------

def get_product_categories(tenant_id: str = "default") -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM product_categories WHERE tenant_id = ? ORDER BY id ASC", (tenant_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def record_product_counting_event(camera_id: str, category: str, direction: str, track_id: int, confidence: float, quantity: int = 1, shift_name: str = "General", snapshot_path: str = "", tenant_id: str = "default"):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    cursor.execute("""
        INSERT INTO product_counting_events (camera_id, product_category, direction, track_id, confidence, quantity, shift_name, timestamp, date, snapshot_path, tenant_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (camera_id, category, direction, track_id, confidence, quantity, shift_name, now_str, date_str, snapshot_path, tenant_id))
    conn.commit()
    conn.close()

def get_product_counting_summary(date_str: Optional[str] = None, tenant_id: str = "default") -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    target_date = date_str or datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        SELECT product_category, SUM(quantity) as total_qty
        FROM product_counting_events
        WHERE date = ? AND tenant_id = ?
        GROUP BY product_category
    """, (target_date, tenant_id))
    rows = cursor.fetchall()
    category_totals = {r["product_category"]: r["total_qty"] for r in rows}

    cursor.execute("SELECT SUM(quantity) FROM product_counting_events WHERE date = ? AND tenant_id = ?", (target_date, tenant_id))
    grand_total = cursor.fetchone()[0] or 0

    conn.close()
    return {
        "date": target_date,
        "total_counted_today": grand_total,
        "category_totals": category_totals
    }
