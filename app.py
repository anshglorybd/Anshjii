import os
from pathlib import Path
from flask import Flask

from config import Config
from database import init_db
from index import index_bp
from admin import admin_bp

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Ensure directories exist
Path(Config.UPLOAD_DIR).mkdir(exist_ok=True)
Path(Config.APPS_DIR).mkdir(exist_ok=True)
Path(Config.NGINX_CONF_DIR).mkdir(parents=True, exist_ok=True)

# Init DB
init_db()

# Register blueprints
app.register_blueprint(index_bp)
app.register_blueprint(admin_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)