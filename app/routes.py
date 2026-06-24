from flask import Blueprint, request, jsonify, render_template, send_from_directory, current_app
from werkzeug.utils import secure_filename
import os
import uuid
from .models import db, ImageTask
from .tasks import validate_tiff_task, run_sam_segmentation

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

ALLOWED_EXTENSIONS = {'tif', 'tiff'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@api_bp.route('/', methods=['GET'])
def home():
    return jsonify({"status": "success", "message": "Demo API Running!"}), 200

@api_bp.route('/viewer', methods=['GET'])
def map_viewer():
    """Serves the frontend HTML map viewer."""
    return render_template('viewer.html')

@api_bp.route('/images/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type. Only TIFF allowed."}), 400
        
    image_id = f"img_{uuid.uuid4().hex[:10]}"
    filename = secure_filename(file.filename)
    filepath = os.path.join('uploads', f"{image_id}_{filename}")
    
    file.save(filepath)
    
    new_task = ImageTask(image_id=image_id, status='uploading', message='File received.')
    db.session.add(new_task)
    db.session.commit()
    
    celery_task = validate_tiff_task.apply_async(args=[image_id, filepath], task_id=new_task.task_id)

    return jsonify({
        "image_id": image_id,
        "task_id": celery_task.id,
        "status": "uploading"
    }), 202

@api_bp.route('/tasks/<task_id>/status', methods=['GET'])
def get_status(task_id):
    task_record = ImageTask.query.get_or_404(task_id)
    celery_task = validate_tiff_task.AsyncResult(task_id)
    
    if celery_task.state == 'PENDING':
        response = {"status": task_record.status, "message": task_record.message}
    elif celery_task.state != 'FAILURE':
        response = {
            "status": celery_task.info.get('status', 'processing'),
            "progress": celery_task.info.get('progress', 0),
            "message": celery_task.info.get('message', '')
        }
    else:
        response = {"status": "failed", "message": str(celery_task.info)}
        
    return jsonify(response), 200

# --- THE SIMPLIFIED FILE SERVING ROUTES ---

@api_bp.route('/uploads/<filename>', methods=['GET'])
def serve_uploaded_file(filename):
    """Serves the raw TIFF file to the frontend."""
    # Force absolute path to avoid directory confusion
    uploads_dir = os.path.abspath('uploads')
    return send_from_directory(uploads_dir, filename)

@api_bp.route('/images/<image_id>/visualization', methods=['GET'])
def get_visualization(image_id):
    """Returns the direct download URL for the frontend georaster plugin."""
    # Force absolute path to match the upload route
    uploads_dir = os.path.abspath('uploads')
    actual_filename = None
    
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            if f.startswith(image_id.strip()): # .strip() removes accidental spaces
                actual_filename = f
                break

    if not actual_filename:
        # This will now tell you EXACTLY which folder it checked
        return jsonify({"error": f"Image file for {image_id} not found. Looked inside: {uploads_dir}"}), 404

    file_url = f"http://127.0.0.1:5000/api/v1/uploads/{actual_filename}"

    return jsonify({
        "image_id": image_id,
        "file_url": file_url
    }), 200

@api_bp.route('/images/<image_id>/segment', methods=['POST'])
def trigger_segmentation(image_id):
    data = request.get_json() or {}
    aoi = data.get('aoi')
    
    if not aoi:
        return jsonify({"error": "AOI GeoJSON is required"}), 400
        
    new_task = ImageTask(image_id=image_id, status='queued', message='AOI received.')
    db.session.add(new_task)
    db.session.commit()
    
    celery_task = run_sam_segmentation.apply_async(args=[image_id, aoi], task_id=new_task.task_id)
    
    return jsonify({
        "task_id": celery_task.id,
        "status": "segmenting",
        "message": "AOI validated. SAM processing initiated."
    }), 202