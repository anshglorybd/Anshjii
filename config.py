import os
import socket
from dotenv import load_dotenv

load_dotenv()


def get_server_ip():
    override = os.getenv("SERVER_IP")
    if override:
        return override
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

    BASE_DOMAIN = os.getenv("BASE_DOMAIN", "kemuhost.local")
    HOSTING_MODE = os.getenv("HOSTING_MODE", "subdomain")

    MAX_APPS_PER_USER = int(os.getenv("MAX_APPS_PER_USER", "5"))
    MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))

    DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "kemu-net")

    APPS_DIR = os.path.abspath("apps_data")
    UPLOAD_DIR = os.path.abspath("uploads")
    NGINX_CONF_DIR = os.path.abspath("nginx/conf.d")

    SERVER_IP = get_server_ip()
    PORT_RANGE_START = int(os.getenv("PORT_RANGE_START", "8000"))
    PORT_RANGE_END = int(os.getenv("PORT_RANGE_END", "9999"))