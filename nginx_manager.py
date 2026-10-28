"""
Auto-generates Nginx config per subdomain:
    <subdomain>.<BASE_DOMAIN>  →  http://127.0.0.1:<port>/
"""
import subprocess
from pathlib import Path
from config import Config

CONF_DIR = Path(Config.NGINX_CONF_DIR)
CONF_DIR.mkdir(parents=True, exist_ok=True)


TEMPLATE = """
# Auto-generated for app: {subdomain}.{base}
server {{
    listen 80;
    server_name {subdomain}.{base};

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_buffering off;
        client_max_body_size 50M;
    }}
}}
"""


def _reload_nginx():
    """Reload nginx inside the docker container"""
    try:
        import docker
        client = docker.from_env()
        try:
            nginx_container = client.containers.get("kemu-nginx")
            nginx_container.exec_run("nginx -t")
            nginx_container.exec_run("nginx -s reload")
            return True
        except docker.errors.NotFound:
            pass
    except Exception as e:
        print(f"Nginx reload warning: {e}")

    try:
        subprocess.run(["nginx", "-s", "reload"], check=True,
                       capture_output=True)
        return True
    except Exception:
        return False


def write_config(subdomain: str, port: int):
    cfg = TEMPLATE.format(
        subdomain=subdomain,
        base=Config.BASE_DOMAIN,
        port=port,
    )
    f = CONF_DIR / f"{subdomain}.conf"
    f.write_text(cfg)
    _reload_nginx()
    return f


def remove_config(subdomain: str):
    f = CONF_DIR / f"{subdomain}.conf"
    if f.exists():
        f.unlink()
        _reload_nginx()


def get_app_url(subdomain: str):
    return f"http://{subdomain}.{Config.BASE_DOMAIN}"