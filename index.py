from pathlib import Path
from flask import (Blueprint, render_template, request, redirect,
                   session, flash, abort, jsonify, send_file)
from werkzeug.utils import secure_filename
from config import Config
import models
import deployer
import nginx_manager
from functools import wraps

index_bp = Blueprint("index", __name__)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return wrapper


# ---------- Landing ----------
@index_bp.route("/")
def landing():
    if "uid" in session:
        return redirect("/dashboard")
    return render_template("landing.html", base_domain=Config.BASE_DOMAIN)


# ---------- Signup ----------
@index_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        u = request.form.get("username", "").strip().lower()
        e = request.form.get("email", "").strip().lower()
        p = request.form.get("password", "")
        if len(u) < 3 or len(p) < 6:
            flash("Username min 3 chars, password min 6 chars", "error")
        else:
            ok, msg = models.create_user(u, e, p)
            if ok:
                flash("✅ Account created. Login now.", "success")
                return redirect("/login")
            flash(f"❌ {msg}", "error")
    return render_template("signup.html")


# ---------- Login ----------
@index_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username", "").strip().lower()
        p = request.form.get("password", "")
        user = models.verify_user(u, p)
        if user:
            session["uid"] = user["id"]
            session["username"] = user["username"]
            session["is_admin"] = bool(user["is_admin"])
            return redirect("/dashboard")
        flash("❌ Invalid credentials", "error")
    return render_template("login.html")


# ---------- Logout ----------
@index_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ---------- Dashboard ----------
@index_bp.route("/dashboard")
@login_required
def dashboard():
    apps = models.get_user_apps(session["uid"])
    user = models.get_user_by_id(session["uid"])
    app_list = []
    for a in apps:
        a = dict(a)
        if a["container_id"]:
            a["stats"] = deployer.get_container_stats(a["container_id"])
        else:
            a["stats"] = {"status": "stopped", "mem_mb": 0, "cpu_pct": 0}
        a["url"] = (nginx_manager.get_app_url(a["subdomain"])
                    if a["status"] == "running" else None)
        app_list.append(a)
    return render_template("dashboard.html", apps=app_list,
                           user=user, base_domain=Config.BASE_DOMAIN)


# ---------- Deploy ----------
@index_bp.route("/deploy", methods=["POST"])
@login_required
def deploy():
    name = secure_filename(request.form.get("name", "").strip().lower())
    file = request.files.get("zipfile")
    env_str = request.form.get("env_vars", "").strip()

    if not file or not file.filename.endswith(".zip"):
        flash("❌ Please upload a .zip file", "error")
        return redirect("/dashboard")
    if not name:
        flash("❌ Invalid app name", "error")
        return redirect("/dashboard")

    user = models.get_user_by_id(session["uid"])
    if models.count_apps(session["uid"]) >= user["app_limit"]:
        flash(f"❌ App limit reached ({user['app_limit']}).", "error")
        return redirect("/dashboard")

    subdomain = f"{session['username']}-{name}"
    db = models.get_db()
    if db.execute("SELECT id FROM apps WHERE subdomain=?", (subdomain,)).fetchone():
        flash("❌ App name already taken", "error")
        return redirect("/dashboard")

    zip_path = Path(Config.UPLOAD_DIR) / f"{subdomain}-{int(__import__('time').time())}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    file.save(zip_path)

    env = {}
    for line in env_str.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    flash("⏳ Building Docker image & installing packages...", "info")
    result = deployer.full_deploy(zip_path, subdomain, env)

    if not result["success"]:
        flash(f"❌ Deploy failed: {result['log'][-300:]}", "error")
        return redirect("/dashboard")

    app_id = models.create_app_record(
        session["uid"], name, subdomain,
        result["port"], result["container_id"], result["entrypoint"]
    )
    models.log_deployment(app_id, result["log"], zip_path)

    # 🔥 Register subdomain in nginx
    nginx_manager.write_config(subdomain, result["port"])

    url = nginx_manager.get_app_url(subdomain)
    flash(f"✅ Deployed! Access at {url}", "success")
    return redirect(f"/app/{app_id}")


# ---------- App detail ----------
@index_bp.route("/app/<int:app_id>")
@login_required
def app_detail(app_id):
    a = models.get_app(app_id, session["uid"])
    if not a:
        abort(404)
    logs = deployer.get_container_logs(a["container_id"]) if a["container_id"] else ""
    stats = deployer.get_container_stats(a["container_id"]) if a["container_id"] else \
            {"status": "stopped", "mem_mb": 0, "cpu_pct": 0}
    deployments = models.get_deployments(app_id)
    url = (nginx_manager.get_app_url(a["subdomain"])
           if a["status"] == "running" else None)
    return render_template("app_detail.html", app=a, logs=logs, stats=stats,
                           deployments=deployments, url=url,
                           base_domain=Config.BASE_DOMAIN)


# ---------- Stop ----------
@index_bp.route("/app/<int:app_id>/stop", methods=["POST"])
@login_required
def stop_app(app_id):
    a = models.get_app(app_id, session["uid"])
    if not a:
        abort(404)
    if a["container_id"]:
        deployer.stop_container(a["container_id"])
    db = models.get_db()
    db.execute("UPDATE apps SET status='stopped', container_id=NULL WHERE id=?",
               (app_id,))
    db.commit()
    nginx_manager.remove_config(a["subdomain"])
    flash("⏹️ App stopped", "success")
    return redirect(f"/app/{app_id}")


# ---------- Start ----------
@index_bp.route("/app/<int:app_id>/start", methods=["POST"])
@login_required
def start_app(app_id):
    a = models.get_app(app_id, session["uid"])
    if not a:
        abort(404)
    if a["container_id"]:
        flash("App already running", "info")
        return redirect(f"/app/{app_id}")
    port = deployer.find_free_port()
    try:
        cid = deployer.run_container(
            f"kemu-app-{a['subdomain']}:latest",
            a["subdomain"], port, {"PORT": "8000"}
        )
    except Exception as e:
        flash(f"❌ Failed to start: {e}", "error")
        return redirect(f"/app/{app_id}")
    db = models.get_db()
    db.execute("UPDATE apps SET status='running', container_id=?, port=? WHERE id=?",
               (cid, port, app_id))
    db.commit()
    nginx_manager.write_config(a["subdomain"], port)
    flash(f"▶️ Started at {nginx_manager.get_app_url(a['subdomain'])}", "success")
    return redirect(f"/app/{app_id}")


# ---------- Delete ----------
@index_bp.route("/app/<int:app_id>/delete", methods=["POST"])
@login_required
def delete_app(app_id):
    a = models.get_app(app_id, session["uid"])
    if not a:
        abort(404)
    if a["container_id"]:
        deployer.stop_container(a["container_id"])
    nginx_manager.remove_config(a["subdomain"])
    import shutil
    shutil.rmtree(Path(Config.APPS_DIR) / a["subdomain"], ignore_errors=True)
    models.delete_app_record(app_id)
    flash("🗑️ App deleted", "success")
    return redirect("/dashboard")


# ---------- Download ZIP ----------
@index_bp.route("/app/<int:app_id>/download")
@login_required
def download_zip(app_id):
    a = models.get_app(app_id, session["uid"])
    if not a:
        abort(404)
    dep = models.get_deployments(app_id)
    if not dep:
        abort(404)
    zip_path = Path(dep[0]["zip_path"])
    if not zip_path.exists():
        abort(404)
    return send_file(zip_path, as_attachment=True,
                     download_name=f"{a['name']}.zip")


# ---------- API: live logs ----------
@index_bp.route("/api/app/<int:app_id>/logs")
@login_required
def api_logs(app_id):
    a = models.get_app(app_id, session["uid"])
    if not a:
        return jsonify({"error": "not found"}), 404
    logs = deployer.get_container_logs(a["container_id"]) if a["container_id"] else ""
    stats = deployer.get_container_stats(a["container_id"]) if a["container_id"] else {"status": "stopped"}
    return jsonify({"logs": logs, "stats": stats})