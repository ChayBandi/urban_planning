from flask import Flask
from flask_cors import CORS
from app.models import db
from app.routes import api_bp
from app.config import Config
import os

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    CORS(app)
    # Initialize plugins
    db.init_app(app)
    
    # Register API endpoints
    app.register_blueprint(api_bp)
    
    # Ensure upload directory exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    with app.app_context():
        # This connects to Postgres and creates the tables automatically
        db.create_all()
        
    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)