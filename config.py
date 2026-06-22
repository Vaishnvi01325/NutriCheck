import os
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

UPLOAD_FOLDER  = os.path.join(BASE_DIR, 'static', 'uploads')
REPORT_FOLDER  = os.path.join(BASE_DIR, 'static', 'reports')
DATABASE_PATH  = os.path.join(BASE_DIR, 'nutricheck.db')

MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB max upload
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'webp'}

# OCR Configuration
OCR_LANGUAGES = ['en']
OCR_GPU = False  # Set True if CUDA-capable GPU available

# Image preprocessing
IMG_MAX_WIDTH  = 1600
IMG_MAX_HEIGHT = 2000

# Health score thresholds
SCORE_HEALTHY  = 70
SCORE_MODERATE = 40

# Nutrient daily reference values (grams, except calories in kcal & sodium in mg)
DAILY_REFERENCE = {
    'calories': 2000,
    'sugar':    50,
    'fat':      65,
    'sodium':   2300,  # mg
    'protein':  50,
    'fiber':    28,
}

# ── Auth & AI ──────────────────────────────────────────────
SECRET_KEY           = os.environ.get('SECRET_KEY', 'nutricheck-dev-secret-change-me')
GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GEMINI_API_KEY       = os.environ.get('GEMINI_API_KEY', '')

