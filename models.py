from database import get_db
from werkzeug.security import generate_password_hash, check_password_hash


def create_user(username, email, password, is_admin=0, plan="free", app_limit=5):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username,email,password_hash,is_admin,plan,app_limit) "
            "VALUES (?,?,?,?,?,?)",
            (username, email, generate_password_hash(password),
             is_admin, plan, app_limit),
        )
        db.commit()
        return True, "Created"
    except Exception as e:
        return False, str(e)


def verify_user(username, password):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if u and check_password_hash(u["password_hash"], password):
        return dict(u)
    return None


def get_user_by_id(uid):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(u) if u else None


def get_user_apps(uid):
    db = get_db()
    return db.execute(
        "SELECT * FROM apps WHERE user_id=? ORDER BY id DESC", (uid,)
    ).fetchall()


def get_app(app_id, uid=None):
    db = get_db()
    if uid is not None:
        a = db.execute(
            "SELECT * FROM apps WHERE id=? AND user_id=?", (app_id, uid)
        ).fetchone()
    else:
        a = db.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
    return dict(a) if a else None


def count_apps(uid):
    db = get_db()
    return db.execute(
        "SELECT COUNT(*) c FROM apps WHERE user_id=?", (uid,)
    ).fetchone()["c"]


def create_app_record(uid, name, subdomain, port, container_id, entrypoint):
    db = get_db()
    cur = db.execute(
        "INSERT INTO apps (user_id,name,subdomain,port,container_id,entrypoint,status) "
        "VALUES (?,?,?,?,?,?,'running')",
        (uid, name, subdomain, port, container_id, entrypoint),
    )
    db.commit()
    return cur.lastrowid


def delete_app_record(app_id):
    db = get_db()
    db.execute("DELETE FROM apps WHERE id=?", (app_id,))
    db.commit()


def log_deployment(app_id, log, zip_path, status="success"):
    db = get_db()
    v = db.execute(
        "SELECT COALESCE(MAX(version),0)+1 v FROM deployments WHERE app_id=?",
        (app_id,),
    ).fetchone()["v"]
    db.execute(
        "INSERT INTO deployments (app_id,version,status,log,zip_path) VALUES (?,?,?,?,?)",
        (app_id, v, status, log[:10000], str(zip_path)),
    )
    db.commit()
    return v


def get_deployments(app_id):
    db = get_db()
    return db.execute(
        "SELECT * FROM deployments WHERE app_id=? ORDER BY id DESC LIMIT 20",
        (app_id,),
    ).fetchall()


def get_all_users():
    db = get_db()
    return db.execute(
        "SELECT id,username,email,plan,created_at,is_admin FROM users ORDER BY id"
    ).fetchall()


def get_all_apps():
    db = get_db()
    return db.execute(
        "SELECT a.*, u.username FROM apps a "
        "JOIN users u ON u.id = a.user_id ORDER BY a.id DESC"
    ).fetchall()