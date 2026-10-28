# TexVision AI - Textile Industry AI Camera Control Center

An enterprise-grade Computer Vision & AI Camera solution built specifically for the **Textile & Saree Manufacturing Industry**.

---

## 🌟 Core System Architecture (3 Modules)

### 🏢 Module 1: 24/7 AI Attendance & Gate Security (Active Focus)
* **24/7 Gate Line-Crossing Detection**: Dual-direction tracking (`IN` and `OUT`) automatically logs entry/exit.
* **Biometric Face ID Recognition**: Deep 576-D face embeddings (YOLOv8-pose keypoints + MobileNetV3 backbone) ensure high-accuracy recognition even with varying lighting or movement.
* **Auto Working Hours Calculator**:
  * First gate `IN` of the day starts the worker's shift timer.
  * Gate `OUT` records the exit time, computes total hours worked, and updates status (`Completed`, `Half-Day`, `Overtime`).
  * Live ongoing hours displayed for all personnel currently inside the mill.
* **Unknown Person Auto-Capture**:
  * Unregistered visitors trigger automatic camera snapshot capture (`/data/unknown_snapshots/`).
  * Logged in "Today's Unknown Persons" section with exact timestamp.
  * 1-Click "Convert to Registered Staff" button to enroll them directly.
* **Printable Attendance Reports**:
  * Filter by Date, Designation, or Status.
  * One-Click **"Print Attendance Sheet"** (`window.print()`) formatted for A4 printing and PDF export.

---

### 🥻 Module 2: Sarees & Taka Bunch Counter (Challan Matching)
* **Raw Taka Bunches**: Handles 20–40 meter fabric rolls brought by delivery boys (1–10 bundles at a time).
* **Finished Sarees Counting**: Handles processed sarees (butta cutting, border cutting, mill processed).
* **Delivery Challan Matching**: Verifies bill challan quantity against counted pieces (e.g. 30, 40, 300, 600 pcs).
* **Discrepancy & Sign-off**: Flags excess or shortage (+/-), and marks signed approval.

---

### 📦 Module 3: Yarn Boxes, Rapier Bimps & Inventory (Anti-Double-Count Lock)
* **Yarn Box Counting**: Tracks inbound/outbound carton boxes.
* **Rapier Bimp (Beam) Tracking**: Tracks heavy machine beams entering the weaving floor.
* **Anti-Double-Count Lock System**: 10-second cooldown lock token prevents the same item from being counted multiple times.

---

## 🚀 Quick Start Guide

### 1. Launching the System
```powershell
cd c:\AiCam
python run.py
```
Open your browser and navigate to:
```
http://localhost:8000
```

### 2. Testing Camera Sources
* **Live Physical Webcam**: Click `📹 Live Webcam` on the control bar.
* **User Gate Video Upload**: Click `📁 Upload Gate Video` to upload your mill entrance CCTV footage (`.mp4`, `.avi`, `.mkv`). The AI immediately switches to analyzing your video file in a continuous loop.
* **Mill Gate Simulation**: Click `🏭 Mill Gate Simulation` to run a synthetic entrance scenario with workers walking in and out.

### 3. Registering New Staff / Workers
1. Click the **Staff & Face ID Registration** tab.
2. Click **➕ Register New Staff Member**.
3. Fill in:
   - **Name** (e.g., *Ramesh Patel*)
   - **Designation** (*Master*, *Weaver*, *Delivery Boy*, *Helper*, *Office Staff*, *Manager*)
   - **Face ID / Code** (e.g., *FC-TXS-101*)
4. Choose **Capture from Webcam** or **Upload Photo File**.
5. Click **Verify Face & Register Staff**. The AI extracts the face embedding and immediately activates 24/7 attendance tracking for that person.

### 4. Viewing & Printing Reports
1. Navigate to the **Daily Working Hours & Reports** tab.
2. Select any date from the calendar.
3. Click **🖨️ Print Official Attendance Sheet** to view and print the clean report with mill header.
