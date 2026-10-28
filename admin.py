from flask import Blueprint, render_template, session, redirect, abort
from functools import wraps
import models
import deployer
import nginx_manager
from config import Config

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "uid" not in session:
            return redirect("/login")
        user = models.get_user_by_id(session["uid"])
        if not user or not user.get("is_admin"):
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@admin_bp.route("/")
@admin_required
def panel():
    users = models.get_all_users()
    apps = models.get_all_apps()

    # Attach stats to each app
    app_list = []
    for a in apps:
        a = dict(a)
        if a.get("container_id"):
            a["stats"] = deployer.get_container_stats(a["container_id"])
        else:
            a["stats"] = {"status": "stopped", "mem_mb": 0, "cpu_pct": 0}
        app_list.append(a)

    total_running = sum(1 for a in app_list if a["status"] == "running")
    return render_template(
        "admin.html",
        users=users,
        apps=app_list,
        base_domain=Config.BASE_DOMAIN,
        total_running=total_running,
    )