import os
import sys
import uvicorn

if __name__ == "__main__":
    print("=" * 65)
    print("  AiCam - TEXTILE INDUSTRY AI CAMERA SYSTEM")
    print("  24/7 Gate Attendance, Saree/Taka & Inventory Management")
    print("=" * 65)
    print("  Server running at: http://localhost:8000")
    print("  Open your browser to access the AI Camera Dashboard!")
    print("=" * 65)
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
