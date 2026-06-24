from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

db = SQLAlchemy()

class ImageTask(db.Model):
    __tablename__ = 'image_tasks'
    
    task_id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    image_id = db.Column(db.String(36), nullable=False)
    status = db.Column(db.String(20), default='uploading')
    progress = db.Column(db.Integer, default=0)
    message = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)