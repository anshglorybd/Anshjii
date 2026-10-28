import os
import shutil
import socket
import time
import zipfile
from pathlib import Path
import docker
from docker.errors import DockerException
from config import Config
from proxy_injector import inject_proxyfix

client = docker.from_env()


def find_free_port(start=None, end=None):
    start = start or Config.PORT_RANGE_START
    end = end or Config.PORT_RANGE_END
    used = set()
    try:
        for c in client.containers.list(all=True):
            ports = (c.attrs.get("NetworkSettings", {}).get("Ports") or {})
            for p in ports.values():
                if p:
                    for binding in p:
                        used.add(int(binding["HostPort"]))
    except Exception:
        pass

    for port in range(start, end):
        if port in used:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in range {start}-{end}")


def safe_extract(zip_path: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            target = os.path.abspath(os.path.join(dest, member))
            if not target.startswith(os.path.abspath(dest)):
                raise Exception(f"Unsafe path in ZIP: {member}")
            info = z.getinfo(member)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise Exception(f"Symlink not allowed: {member}")
        z.extractall(dest)

    items = list(dest.iterdir())
    if len(items) == 1 and items[0].is_dir():
        nested = items[0]
        for f in nested.iterdir():
            shutil.move(str(f), str(dest / f.name))
        nested.rmdir()


def detect_entrypoint(app_dir: Path):
    for cand in ["app.py", "main.py", "run.py", "server.py", "wsgi.py", "index.py"]:
        if (app_dir / cand).exists():
            return cand
    for f in app_dir.glob("*.py"):
        try:
            if "Flask(" in f.read_text(errors="ignore"):
                return f.name
        except Exception:
            continue
    raise Exception("❌ No entrypoint found (need app.py/main.py/index.py)")


def generate_dockerfile(app_dir: Path, entrypoint: str):
    df = app_dir / "Dockerfile.kemu"
    has_req = (app_dir / "requirements.txt").exists()

    use_gunicorn = False
    try:
        content = (app_dir / entrypoint).read_text(errors="ignore")
        if "Flask(" in content and "app.run" not in content:
            use_gunicorn = True
    except Exception:
        pass

    module = entrypoint.replace(".py", "")
    if use_gunicorn:
        cmd = f'["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "--timeout", "120", "{module}:app"]'
    else:
        cmd = f'["python", "{entrypoint}"]'

    install = "RUN pip install --no-cache-dir -r requirements.txt" if has_req else ""

    df.write_text(f"""FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt* /app/
{install}
COPY . /app/
EXPOSE 8000
CMD {cmd}
""")
    return df


def build_image(app_dir: Path, tag: str):
    logs = []
    try:
        image, build_logs = client.images.build(
            path=str(app_dir),
            dockerfile="Dockerfile.kemu",
            tag=tag,
            rm=True,
            forcerm=True,
        )
        for chunk in build_logs:
            if "stream" in chunk:
                logs.append(chunk["stream"].strip())
            if "error" in chunk:
                logs.append("ERROR: " + chunk["error"])
        return image, "\n".join([l for l in logs if l])
    except docker.errors.BuildError as e:
        err = "\n".join([str(l) for l in e.build_log])
        return None, err


def run_container(image_tag: str, app_name: str, port: int,
                  env: dict, mem_mb=256, cpu=0.5):
    try:
        client.networks.get(Config.DOCKER_NETWORK)
    except docker.errors.NotFound:
        client.networks.create(Config.DOCKER_NETWORK, driver="bridge")

    # Remove old container with same name
    try:
        old = client.containers.get(f"kemu-{app_name}")
        old.stop(timeout=3)
        old.remove(force=True)
    except docker.errors.NotFound:
        pass

    container = client.containers.run(
        image_tag,
        detach=True,
        name=f"kemu-{app_name}",
        ports={"8000/tcp": port},
        environment=env,
        mem_limit=f"{mem_mb}m",
        memswap_limit=f"{mem_mb}m",
        nano_cpus=int(cpu * 1e9),
        network=Config.DOCKER_NETWORK,
        restart_policy={"Name": "unless-stopped"},
        labels={"kemu.app": app_name},
        security_opt=["no-new-privileges"],
        cap_drop=["ALL"],
    )
    time.sleep(3)
    return container.id


def stop_container(container_id: str):
    try:
        c = client.containers.get(container_id)
        c.stop(timeout=5)
        c.remove(force=True)
    except docker.errors.NotFound:
        pass


def get_container_logs(container_id: str, tail=200):
    try:
        c = client.containers.get(container_id)
        return c.logs(tail=tail).decode(errors="ignore")
    except Exception as e:
        return f"(no logs: {e})"


def get_container_stats(container_id: str):
    try:
        c = client.containers.get(container_id)
        stats = c.stats(stream=False)
        mem = stats["memory_stats"].get("usage", 0) / 1024 / 1024
        cpu_delta = (stats["cpu_stats"]["cpu_usage"]["total_usage"]
                     - stats["precpu_stats"]["cpu_usage"]["total_usage"])
        sys_delta = (stats["cpu_stats"]["system_cpu_usage"]
                     - stats["precpu_stats"]["system_cpu_usage"])
        cpu_pct = 0
        if sys_delta > 0:
            cpu_pct = (cpu_delta / sys_delta) * 100
        return {"mem_mb": round(mem, 1), "cpu_pct": round(cpu_pct, 1),
                "status": c.status}
    except Exception:
        return {"mem_mb": 0, "cpu_pct": 0, "status": "unknown"}


def full_deploy(zip_path: Path, app_name: str, user_env: dict = None):
    workdir = Path(Config.APPS_DIR) / app_name
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    safe_extract(zip_path, workdir)

    # 🔥 Auto-inject ProxyFix
    try:
        inject_proxyfix(workdir)
    except Exception as e:
        print(f"ProxyFix injection warning: {e}")

    entry = detect_entrypoint(workdir)
    generate_dockerfile(workdir, entry)

    image_tag = f"kemu-app-{app_name}:latest"
    image, build_log = build_image(workdir, image_tag)
    if not image:
        return {"success": False, "log": build_log}

    port = find_free_port()
    env = {"PORT": "8000", "PYTHONUNBUFFERED": "1"}
    if user_env:
        env.update(user_env)

    try:
        cid = run_container(image_tag, app_name, port, env)
    except Exception as e:
        return {"success": False, "log": f"Container start failed: {e}"}

    return {
        "success": True,
        "container_id": cid,
        "port": port,
        "entrypoint": entry,
        "log": build_log,
    }