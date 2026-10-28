import sqlite3
from pathlib import Path

DB_PATH = Path("hosting.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        plan TEXT DEFAULT 'free',
        app_limit INTEGER DEFAULT 5
    );

    CREATE TABLE IF NOT EXISTS apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        subdomain TEXT UNIQUE NOT NULL,
        container_id TEXT,
        port INTEGER,
        status TEXT DEFAULT 'building',
        entrypoint TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        cpu_limit REAL DEFAULT 0.5,
        mem_limit_mb INTEGER DEFAULT 256,
        env_vars TEXT DEFAULT '{}',
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, name)
    );

    CREATE TABLE IF NOT EXISTS deployments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id INTEGER NOT NULL,
        version INTEGER NOT NULL,
        status TEXT,
        log TEXT,
        zip_path TEXT,
        deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (app_id) REFERENCES apps(id) ON DELETE CASCADE
    );
    """)
    conn.commit()

    from config import Config
    from werkzeug.security import generate_password_hash

    existing = conn.execute(
        "SELECT id FROM users WHERE username=?", (Config.ADMIN_USERNAME,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users (username,email,password_hash,is_admin,plan,app_limit) VALUES (?,?,?,?,?,?)",
            (Config.ADMIN_USERNAME,
             f"{Config.ADMIN_USERNAME}@kemu.local",
             generate_password_hash(Config.ADMIN_PASSWORD),
             1, "admin", 999),
        )
        conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("✅ DB initialized")