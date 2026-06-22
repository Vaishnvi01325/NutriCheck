import os
import sys
import time
import signal

# Suppress EasyOCR/PyTorch pin_memory warning on CPU-only machines
os.environ.setdefault('PYTORCH_NO_CUDA_MEMORY_CACHING', '1')

# Fix Windows encoding issue with EasyOCR's Unicode progress bar characters
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from flask import (
    Flask, request, jsonify, send_file,
    render_template, redirect, url_for, session
)
from werkzeug.utils import secure_filename
from authlib.integrations.flask_client import OAuth
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)

from config import (
    UPLOAD_FOLDER, MAX_CONTENT_LENGTH, ALLOWED_EXTENSIONS,
    SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
)
from database import (
    init_db, get_all_analyses, get_analysis_by_id,
    delete_analysis, get_analyses_by_ids,
    get_or_create_user, get_user_by_id, save_analysis,
)
from services.analysis_service import analyze_image
from services.pdf_service import generate_pdf
from services.ocr_service import warm_up as warm_up_ocr
from models.dnn_scorer import warm_up as warm_up_dnn

# ─────────────────────────────────────────────────────────
# Flask App Setup
# ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────────────────
# Flask-Login
# ─────────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = 'login_page'
login_manager.login_message = ''


class User(UserMixin):
    def __init__(self, id, name, email, avatar):
        self.id     = id
        self.name   = name
        self.email  = email
        self.avatar = avatar


@login_manager.user_loader
def load_user(user_id):
    data = get_user_by_id(int(user_id))
    if data:
        return User(data['id'], data['name'], data['email'], data['avatar_url'])
    return None


# ─────────────────────────────────────────────────────────
# Google OAuth (Authlib)
# ─────────────────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)


# ─────────────────────────────────────────────────────────
# Auth Routes
# ─────────────────────────────────────────────────────────

@app.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/login/google')
def google_login():
    redirect_uri = "http://localhost:5000/auth/google/callback"
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/google/callback')
def google_callback():
    try:
        token     = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            return redirect(url_for('login_page') + '?error=1')

        user_data = get_or_create_user(
            google_id  = user_info['sub'],
            email      = user_info.get('email', ''),
            name       = user_info.get('name', 'User'),
            avatar_url = user_info.get('picture', ''),
        )
        user = User(
            user_data['id'], user_data['name'],
            user_data['email'], user_data['avatar_url']
        )
        login_user(user, remember=True)
        return redirect(url_for('index'))
    except Exception as e:
        print(f"[Auth] Google callback error: {e}")
        return redirect(url_for('login_page') + '?error=1')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login_page'))


# ─────────────────────────────────────────────────────────
# Main App Routes
# ─────────────────────────────────────────────────────────

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/')
@login_required
def index():
    return render_template('index.html', user=current_user)


# ─────────────────────────────────────────────────────────
# Analysis API
# ─────────────────────────────────────────────────────────

@app.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    """Upload an image and run full analysis pipeline."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': f'File type not allowed. Use: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    filename = secure_filename(file.filename)
    name, ext = os.path.splitext(filename)
    filename  = f"{name}_{int(time.time())}{ext}"
    filepath  = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # ── Dimension guard: reject absurdly large images before OCR ──────
    try:
        import cv2 as _cv2
        _img_check = _cv2.imread(filepath)
        if _img_check is not None:
            _h, _w = _img_check.shape[:2]
            if _w > 6000 or _h > 8000:
                os.remove(filepath)
                return jsonify({'error': (
                    f'Image is too large ({_w}×{_h}px). '
                    'Please resize it to under 4000×5000px before uploading. '
                    'Most phone screenshots or label scans are fine — this is usually a raw camera photo.'
                )}), 413
    except Exception:
        pass  # dimension check failed — let OCR try anyway

    try:
        user_id = current_user.id
    except AttributeError:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        result = analyze_image(filepath, user_id=user_id)
        result['image_url'] = f'/static/uploads/{filename}'
        result.pop('breakdown', None)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': f'Analysis failed: {str(e)}'}), 500


@app.route('/api/history', methods=['GET'])
@login_required
def api_history():
    """Return analysis history for the logged-in user."""
    try:
        user_id = current_user.id
    except AttributeError:
        return jsonify({'error': 'Not authenticated'}), 401
    analyses = get_all_analyses(user_id=user_id)
    for a in analyses:
        if a.get('image_path'):
            a['image_url'] = '/static/uploads/' + os.path.basename(a['image_path'])
    return jsonify(analyses), 200


@app.route('/api/analysis/<int:analysis_id>', methods=['GET'])
@login_required
def api_get_analysis(analysis_id):
    analysis = get_analysis_by_id(analysis_id)
    if not analysis:
        return jsonify({'error': 'Analysis not found'}), 404
    if analysis.get('image_path'):
        analysis['image_url'] = '/static/uploads/' + os.path.basename(analysis['image_path'])
    return jsonify(analysis), 200


@app.route('/api/analysis/<int:analysis_id>', methods=['DELETE'])
@login_required
def api_delete_analysis(analysis_id):
    deleted = delete_analysis(analysis_id)
    if deleted:
        return jsonify({'message': 'Deleted successfully'}), 200
    return jsonify({'error': 'Analysis not found'}), 404


@app.route('/api/compare', methods=['POST'])
@login_required
def api_compare():
    data = request.get_json()
    if not data or 'ids' not in data:
        return jsonify({'error': 'Provide list of analysis IDs'}), 400
    ids = data['ids']
    if len(ids) < 2:
        return jsonify({'error': 'Need at least 2 products to compare'}), 400

    analyses = get_analyses_by_ids(ids)
    for a in analyses:
        if a.get('image_path'):
            a['image_url'] = '/static/uploads/' + os.path.basename(a['image_path'])
    return jsonify(analyses), 200


@app.route('/api/report/<int:analysis_id>', methods=['GET'])
@login_required
def api_report(analysis_id):
    analysis = get_analysis_by_id(analysis_id)
    if not analysis:
        return jsonify({'error': 'Analysis not found'}), 404
    try:
        pdf_path = generate_pdf(analysis)
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f'nutricheck_report_{analysis_id}.pdf',
            mimetype='application/pdf',
        )
    except Exception as e:
        return jsonify({'error': f'PDF generation failed: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────
# Debug OCR Endpoint (development only)
# ─────────────────────────────────────────────────────────

@app.route('/api/debug-ocr', methods=['POST'])
@login_required
def api_debug_ocr():
    """
    Debug endpoint: returns raw OCR + spatial parsing details.
    Upload an image and see exactly what was detected and how it was parsed.
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400

    file = request.files['image']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type'}), 400

    filename = f"debug_{int(time.time())}.jpg"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    try:
        from services.ocr_service import extract_with_bboxes
        from models.nutrient_parser import (
            _group_into_rows, _merge_decimal_fragments,
            _detect_column_anchors, _extract_rows,
            _cross_validate, _sanity_check,
        )

        ocr_items, image_width, image_height = extract_with_bboxes(filepath)
        rows = _group_into_rows(ocr_items, tolerance_px=22)
        rows = [_merge_decimal_fragments(row) for row in rows]
        per_100g_x, per_serve_x = _detect_column_anchors(rows, image_width)
        nutrients, carbs = _extract_rows(rows, per_100g_x, per_serve_x, image_width)
        nutrients = _cross_validate(nutrients, carbs)
        nutrients = _sanity_check(nutrients)

        return jsonify({
            'image_width': image_width,
            'image_height': image_height,
            'per_100g_column_x': per_100g_x,
            'per_serve_column_x': per_serve_x,
            'detected_carbohydrates': carbs,
            'parsed_nutrients': nutrients,
            'total_items': len(ocr_items),
            'total_rows': len(rows),
            'rows': [
                [{'text': i['text'], 'cx': round(i['cx']), 'cy': round(i['cy']), 'conf': round(i['conf'], 2)}
                 for i in row]
                for row in rows
            ]
        }), 200
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


# ─────────────────────────────────────────────────────────
# RAG Chatbot API
# ─────────────────────────────────────────────────────────

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Handle chatbot messages using RAG + Gemini."""
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Provide a message'}), 400

    user_message     = data['message'].strip()
    analysis_context = data.get('analysis_context')  # Optional: current scan result

    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    try:
        from services.rag_service import chat
        reply = chat(user_message, analysis_context=analysis_context)
        return jsonify({'reply': reply}), 200
    except Exception as e:
        return jsonify({'error': f'Chat error: {str(e)}'}), 500


# ─────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    # ── Startup Initialization ─────────────────────────────────────
    print("\n" + "="*50)
    print(" NutriCheck — Starting intelligence platform…")
    print("="*50 + "\n")

    init_db()

    # Pre-warm OCR and AI models so first request is fast
    # This might take 30-60s on first run if models need downloading
    try:
        warm_up_ocr()
        warm_up_dnn()
    except Exception as e:
        print(f"[NutriCheck] Warning: Startup warm-up failed: {e}")

    print("\n[NutriCheck] Server is ready to receive requests!")
    print("Dashboard: http://127.0.0.1:5000\n")

    app.run(debug=False, host='0.0.0.0', port=5000)
