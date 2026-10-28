"""
Injects ProxyFix into user's Flask app so path/subdomain routing
works without user modifying their code.
"""
from pathlib import Path

PROXYFIX_SNIPPET = '''
# --- KEMU HOSTING BOT: auto-injected ProxyFix ---
try:
    from werkzeug.middleware.proxy_fix import ProxyFix as _KemuProxyFix
    if hasattr(app, "wsgi_app"):
        app.wsgi_app = _KemuProxyFix(app.wsgi_app, x_for=1, x_proto=1,
                                     x_host=1, x_prefix=1)
except Exception:
    pass
# --- end KEMU injection ---
'''


def inject_proxyfix(app_dir: Path):
    """
    Search for 'app = Flask(...)' in any .py file and inject ProxyFix
    right after it. Safe to run multiple times.
    """
    if not app_dir.exists():
        return False

    candidates = ["app.py", "main.py", "run.py", "server.py", "wsgi.py",
                  "__init__.py", "index.py"]
    py_files = []
    for c in candidates:
        p = app_dir / c
        if p.exists():
            py_files.append(p)

    # Also check nested packages
    for p in app_dir.rglob("*.py"):
        if p not in py_files and p.name != "_kemu_runner.py":
            py_files.append(p)

    injected = False
    for py in py_files:
        try:
            content = py.read_text(errors="ignore")
        except Exception:
            continue

        if "KEMU HOSTING BOT: auto-injected" in content:
            continue  # already injected

        if "app = Flask(" not in content and "app=Flask(" not in content:
            continue

        # Find line with Flask init
        lines = content.splitlines()
        out_lines = []
        for line in lines:
            out_lines.append(line)
            if ("app = Flask(" in line or "app=Flask(" in line) and not line.strip().startswith("#"):
                out_lines.append(PROXYFIX_SNIPPET)

        py.write_text("\n".join(out_lines))
        injected = True

    return injected