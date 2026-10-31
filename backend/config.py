import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
FRONTEND_DIR = BASE_DIR / "frontend"

STAFF_PHOTOS_DIR = DATA_DIR / "staff_photos"
UNKNOWN_SNAPSHOTS_DIR = DATA_DIR / "unknown_snapshots"
UPLOADED_VIDEOS_DIR = DATA_DIR / "uploaded_videos"
DB_PATH = DATA_DIR / "aicam.db"

# Create directories if they do not exist
for d in [DATA_DIR, MODELS_DIR, FRONTEND_DIR, STAFF_PHOTOS_DIR, UNKNOWN_SNAPSHOTS_DIR, UPLOADED_VIDEOS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Application Settings
APP_NAME = "AiCam Camera Control Center"
VERSION = "1.0.0"

# Camera & Detection Settings
CAMERA_INDEX = 0  # Default webcam
DEFAULT_CONFIDENCE_THRESHOLD = 0.50
FACE_MATCH_THRESHOLD = 0.58  # Cosine similarity / distance threshold for face recognition
LINE_CROSSING_BUFFER = 25  # pixel margin for line crossing in/out logic
LOCK_DOUBLE_COUNT_COOLDOWN = 10.0  # seconds to prevent duplicate counting of same person/object

# Textile Industry Specific Settings
TAKA_AVERAGE_LENGTH_METERS = 30  # 20-40 meters typical bunch
ENABLE_VOICE_ALERT = True
