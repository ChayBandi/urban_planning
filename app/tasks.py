from celery import Celery
import time
import os

celery_app = Celery('tasks', broker='redis://localhost:6379/0', backend='redis://localhost:6379/0')

@celery_app.task(bind=True)
def validate_tiff_task(self, image_id, file_path):
    self.update_state(state='PROGRESS', meta={'status': 'validating', 'progress': 20, 'message': 'Extracting metadata...'})
    
    # Simulate extraction time
    time.sleep(2) 
    
    # In a real scenario, you call validate_and_get_tiff_metadata() from utils here
    # Mocking Ahmedabad bounds for example
    bounds = [72.4, 22.9, 72.7, 23.1] 
    
    return {'status': 'ready_for_visualization', 'bounds': bounds, 'image_id': image_id}

@celery_app.task(bind=True)
def run_sam_segmentation(self, image_id, aoi_geojson):
    self.update_state(state='PROGRESS', meta={'status': 'segmenting', 'progress': 10, 'message': 'Padding AOI to SAM format...'})
    
    # Simulate heavy SAM model inference
    time.sleep(5)
    
    self.update_state(state='PROGRESS', meta={'status': 'segmenting', 'progress': 80, 'message': 'Generating vector masks...'})
    time.sleep(2)
    
    return {'status': 'completed', 'message': 'Segmentation successful', 'result_geojson': '...'}