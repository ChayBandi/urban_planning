from flask import Blueprint, request, jsonify, render_template, send_from_directory, current_app
from werkzeug.utils import secure_filename
import os
import uuid
import threading
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
    
    uploads_dir = os.path.abspath('uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    filepath = os.path.join(uploads_dir, f"{image_id}_{filename}")
    
    file.save(filepath)
    
    new_task = ImageTask(image_id=image_id, status='uploading', message='File received.')
    db.session.add(new_task)
    db.session.commit()
    
    # NEW: Run in a pure Python background thread!
    app_context = current_app._get_current_object()
    thread = threading.Thread(target=validate_tiff_task, args=(app_context, new_task.task_id, image_id, filepath))
    thread.start()

    return jsonify({
        "image_id": image_id,
        "task_id": new_task.task_id,
        "status": "uploading"
    }), 202

@api_bp.route('/tasks/<task_id>/status', methods=['GET'])
def get_status(task_id):
    """Polls the SQLite database for the status."""
    task_record = ImageTask.query.get_or_404(task_id)
    
    response = {
        "status": task_record.status,
        "message": task_record.message
    }
    
    # If the thread marked it as finished, dynamically assemble the mask URLs
    if task_record.status == 'finished':
        prompts = ["building", "road", "vegetation"]
        masks = {}
        outputs_dir = os.path.abspath('outputs')
        
        for prompt in prompts:
            expected_filename = f"mask_{task_record.image_id}_{prompt}.tif"
            if os.path.exists(os.path.join(outputs_dir, expected_filename)):
                masks[prompt] = f"http://127.0.0.1:5000/api/v1/outputs/{expected_filename}"
                
        response["result"] = {"masks": masks}
        
    return jsonify(response), 200

# --- THE FILE SERVING ROUTES ---

@api_bp.route('/uploads/<filename>', methods=['GET'])
def serve_uploaded_file(filename):
    uploads_dir = os.path.abspath('uploads')
    return send_from_directory(uploads_dir, filename)

@api_bp.route('/outputs/<filename>', methods=['GET'])
def serve_output_file(filename):
    outputs_dir = os.path.abspath('outputs')
    return send_from_directory(outputs_dir, filename)

@api_bp.route('/images/<image_id>/visualization', methods=['GET'])
def get_visualization(image_id):
    uploads_dir = os.path.abspath('uploads')
    actual_filename = None
    
    if os.path.exists(uploads_dir):
        for f in os.listdir(uploads_dir):
            if f.startswith(image_id.strip()): 
                actual_filename = f
                break

    if not actual_filename:
        return jsonify({"error": f"Image file for {image_id} not found."}), 404

    return jsonify({
        "image_id": image_id,
        "file_url": f"http://127.0.0.1:5000/api/v1/uploads/{actual_filename}"
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
    
    # NEW: Run in a pure Python background thread!
    app_context = current_app._get_current_object()
    thread = threading.Thread(target=run_sam_segmentation, args=(app_context, new_task.task_id, image_id, aoi))
    thread.start()
    
    return jsonify({
        "task_id": new_task.task_id,
        "status": "segmenting",
        "message": "AOI validated. SAM processing initiated."
    }), 202