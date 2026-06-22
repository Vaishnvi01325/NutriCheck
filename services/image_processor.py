"""
Image Preprocessing Pipeline — NutriCheck
==========================================
Optimized for food nutrition label photos taken with smartphones:
- Labels often have colored text (blue, green, red) on light backgrounds
- Images may be slightly tilted, blurry, or have uneven lighting
- Table layouts require good column separation for OCR

Pipeline produces MULTIPLE versions of the preprocessed image for
multi-pass OCR (each version optimized for different label styles).
"""

import cv2
import numpy as np
from config import IMG_MAX_WIDTH, IMG_MAX_HEIGHT


# ─────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────

def preprocess_image(image_path: str) -> np.ndarray:
    """
    Main preprocessing pipeline.
    Returns the BEST single preprocessed image (numpy array) for OCR.
    For multi-pass OCR, use get_all_preprocessed_versions().
    """
    img = _load_and_upscale(image_path)
    versions = _generate_versions(img)
    # Return the high-contrast binary version as primary
    return versions['binary_otsu']


def get_all_preprocessed_versions(image_path: str) -> dict:
    """
    Generate all preprocessing variants for multi-pass OCR.
    Returns a dict of {name: numpy_array}.
    """
    img = _load_and_upscale(image_path)
    return _generate_versions(img)


# ─────────────────────────────────────────────────────────
# Internal Pipeline
# ─────────────────────────────────────────────────────────

def _load_and_upscale(image_path: str) -> np.ndarray:
    """Load image and upscale small images for better OCR accuracy."""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    h, w = img.shape[:2]

    # Upscale images that are too small — EasyOCR works best on 1600+ px wide images
    # Raised from 1200 → 1600 for significantly better small-text detection
    MIN_WIDTH = 1600
    if w < MIN_WIDTH:
        scale = MIN_WIDTH / w
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]

    # Cap at max dimensions to avoid memory issues
    if w > IMG_MAX_WIDTH or h > IMG_MAX_HEIGHT:
        img = _resize_keep_aspect(img, IMG_MAX_WIDTH, IMG_MAX_HEIGHT)

    # Add white border padding — text at the very edge of a photo is often
    # partially clipped, causing the rightmost numeric value in a row to vanish.
    BORDER = 20
    img = cv2.copyMakeBorder(img, BORDER, BORDER, BORDER, BORDER,
                              cv2.BORDER_CONSTANT, value=(255, 255, 255))

    return img


def _generate_versions(img: np.ndarray) -> dict:
    """
    Generate multiple preprocessed versions of the image.
    Different versions work better for different label colors/styles.
    """
    versions = {}

    # ── Version 1: Red channel extraction ────────────────────────────
    # Blue/dark text on white: the RED channel shows blue text as DARK
    # (since blue pixels have low red values). Best for blue-text labels.
    red_channel = img[:, :, 2]   # OpenCV is BGR; index 2 = Red
    versions['red_channel'] = _clean_binary(red_channel, block=25, C=10)

    # ── Version 2: Standard grayscale + Otsu ─────────────────────────
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary_otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    versions['binary_otsu'] = binary_otsu

    # ── Version 3: CLAHE + adaptive threshold ────────────────────────
    # Good for uneven lighting (common in phone photos)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    clahe_img = clahe.apply(gray)
    adaptive = cv2.adaptiveThreshold(
        clahe_img, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=8
    )
    versions['clahe_adaptive'] = adaptive

    # ── Version 4: Inverted (for dark backgrounds with light text) ────
    versions['inverted'] = cv2.bitwise_not(binary_otsu)

    # ── Version 5: Sharpened grayscale ──────────────────────────────
    kernel_sharpen = np.array([
        [0,  -1,  0],
        [-1,  5, -1],
        [0,  -1,  0],
    ])
    sharpened = cv2.filter2D(gray, -1, kernel_sharpen)
    _, sharp_binary = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    versions['sharpened'] = sharp_binary

    # ── Version 6: Deskewed ──────────────────────────────────────────
    # Correct slight rotation — critical for table-format labels
    deskewed = _deskew(gray)
    _, deskew_binary = cv2.threshold(deskewed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    versions['deskewed'] = deskew_binary

    # ── Version 7: Gamma-corrected ───────────────────────────────────
    # Brightens underexposed photos (common in bad lighting).
    # Many missed sodium/fiber readings come from low-contrast dark images.
    gamma_corrected = _apply_gamma(gray, gamma=1.5)
    _, gamma_binary = cv2.threshold(gamma_corrected, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    versions['gamma_corrected'] = gamma_binary

    # ── Version 8: Morphological close ───────────────────────────────
    # Closes small pixel gaps in thin text characters (especially digits
    # 1, 7, and ':' which commonly get gaps causing misreads).
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morph_closed = cv2.morphologyEx(binary_otsu, cv2.MORPH_CLOSE, kernel_close)
    versions['morphological_close'] = morph_closed

    return versions


def _apply_gamma(gray: np.ndarray, gamma: float = 1.5) -> np.ndarray:
    """Apply gamma correction to brighten or darken an image."""
    inv_gamma = 1.0 / gamma
    table = np.array([
        ((i / 255.0) ** inv_gamma) * 255
        for i in np.arange(0, 256)
    ]).astype('uint8')
    return cv2.LUT(gray, table)


def _clean_binary(gray: np.ndarray, block: int = 21, C: int = 8) -> np.ndarray:
    """Apply denoising + adaptive threshold to a grayscale image."""
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=block,
        C=C
    )
    # Morphological opening to remove tiny noise blobs
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """
    Detect and correct image tilt up to ±15 degrees.
    Uses Hough line detection on edges to estimate skew angle.
    """
    try:
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                minLineLength=gray.shape[1] // 4,
                                maxLineGap=20)
        if lines is None:
            return gray

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 == 0:
                continue
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # Only consider nearly horizontal lines (text rows)
            if abs(angle) < 15:
                angles.append(angle)

        if not angles:
            return gray

        median_angle = float(np.median(angles))
        # Don't rotate if already mostly straight (within 0.3 degrees)
        if abs(median_angle) < 0.3:
            return gray

        h, w = gray.shape
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        rotated = cv2.warpAffine(gray, M, (w, h),
                                 flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)
        return rotated
    except Exception:
        return gray


def _resize_keep_aspect(img: np.ndarray, max_w: int, max_h: int) -> np.ndarray:
    """Resize to fit within bounds, preserving aspect ratio."""
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h)
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


# ─────────────────────────────────────────────────────────
# Legacy / Public Helpers
# ─────────────────────────────────────────────────────────

def resize_image(img, max_width, max_height):
    """Public resize helper (used by pdf_service)."""
    return _resize_keep_aspect(img, max_width, max_height)


def get_image_for_display(image_path):
    """Read and resize original image for PDF/display (keeps color)."""
    img = cv2.imread(image_path)
    if img is None:
        return None
    return _resize_keep_aspect(img, 600, 800)
