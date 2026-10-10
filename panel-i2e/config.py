"""
Configuración del Panel de Control I2E.

Este módulo carga valores por defecto genéricos.
Si existe `config.local.py` (ignorado por git), sus valores
SOBREESCRIBEN los defaults — es la única personalización que
el usuario necesita hacer por clúster.
"""
import os
from pathlib import Path
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).parent


# ══════════════════════════════════════════════════════════════
#  Defaults genéricos
#  (sobreescribibles desde config.local.py)
# ══════════════════════════════════════════════════════════════
class _Defaults:
    # ─── Nodos ────────────────────────────────────────────────
    MANAGER_IP   = "10.4.8.10"
    WORKER_IPS   = []
    NAS_IP       = "10.4.8.19"

    # ─── Rutas ────────────────────────────────────────────────
    ANSIBLE_DIR  = "/home/cluster0/cluster-i2e"
    NAS_BASE     = "/srv/nas/home-panel"
    MAC_SCRIPT   = "/home/cluster0/Mac/Mac.sh"

    # ─── Panel ────────────────────────────────────────────────
    PORT_PANEL   = 7000
    SSH_USER     = "cluster0"

    # ─── Admin inicial ────────────────────────────────────────
    ADMIN_USER     = "Cluster0"
    ADMIN_PASSWORD = "oxoCluster0"

    # ─── Flask ────────────────────────────────────────────────
    SECRET_KEY   = "cambia-esto-en-config-local"

    # ─── NAS ──────────────────────────────────────────────────
    NAS_MAX_UPLOAD_MB = 2048

    # ─── Puertos de apps ──────────────────────────────────────
    PORT_JUPYTER    = 8888
    PORT_SPARK_UI   = 8080
    PORT_SPARK      = 7077
    PORT_RAY_DASH   = 8265
    PORT_RAY        = 6380
    PORT_PORTAINER  = 9443
    PORT_TTYD       = 7681


# ══════════════════════════════════════════════════════════════
#  Cargar config.local.py si existe
# ══════════════════════════════════════════════════════════════
_LOCAL = None
_LOCAL_PATH = BASE_DIR / "config.local.py"

if _LOCAL_PATH.exists():
    try:
        import importlib.util
        _spec = importlib.util.spec_from_file_location("config_local", _LOCAL_PATH)
        _LOCAL = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_LOCAL)
        print(f"[config] cargado {_LOCAL_PATH.name}")
    except Exception as e:
        print(f"[config] ERROR cargando {_LOCAL_PATH.name}: {e}")
        print("[config] usando defaults")


def _get(name, default):
    """Devuelve el valor de config.local.py si existe, si no el default."""
    if _LOCAL is not None:
        val = getattr(_LOCAL, name, None)
        if val is not None:
            return val
    return default


# ══════════════════════════════════════════════════════════════
#  Clase Config pública (consumida por toda la app)
# ══════════════════════════════════════════════════════════════
class Config:
    # ─── Flask ────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("PANEL_SECRET_KEY") or _get(
        "SECRET_KEY", _Defaults.SECRET_KEY)
    DATA_DIR = str(BASE_DIR / "data")
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600 * 4

    # ─── Nodos del clúster ────────────────────────────────────
    MANAGER_IP   = _get("MANAGER_IP",   _Defaults.MANAGER_IP)
    WORKER_IPS   = _get("WORKER_IPS",   _Defaults.WORKER_IPS)
    NAS_IP       = _get("NAS_IP",       _Defaults.NAS_IP)
    SSH_USER     = _get("SSH_USER",     _Defaults.SSH_USER)

    # ─── Rutas Ansible ────────────────────────────────────────
    ANSIBLE_DIR = _get("ANSIBLE_DIR", _Defaults.ANSIBLE_DIR)
    INVENTORY   = f"{ANSIBLE_DIR}/hosts"
    USERS_YAML  = f"{ANSIBLE_DIR}/users/users.yaml"
    PLAYBOOKS   = f"{ANSIBLE_DIR}/playbooks"
    AUDIT_LOG   = str(BASE_DIR / "data" / "audit.jsonl")

    # ─── NAS / scripts ────────────────────────────────────────
    NAS_BASE      = _get("NAS_BASE",    _Defaults.NAS_BASE)
    MAC_SCRIPT    = _get("MAC_SCRIPT",  _Defaults.MAC_SCRIPT)
    NAS_MAX_UPLOAD_MB = _get("NAS_MAX_UPLOAD_MB", _Defaults.NAS_MAX_UPLOAD_MB)

    # ─── Panel ────────────────────────────────────────────────
    PORT_PANEL  = _get("PORT_PANEL", _Defaults.PORT_PANEL)

    # ─── Admin inicial ────────────────────────────────────────
    ADMIN_USER     = _get("ADMIN_USER",     _Defaults.ADMIN_USER)
    ADMIN_PASSWORD = _get("ADMIN_PASSWORD", _Defaults.ADMIN_PASSWORD)

    # ─── Puertos de aplicaciones ──────────────────────────────
    PORT_JUPYTER    = _get("PORT_JUPYTER",   _Defaults.PORT_JUPYTER)
    PORT_SPARK_UI   = _get("PORT_SPARK_UI",  _Defaults.PORT_SPARK_UI)
    PORT_SPARK      = _get("PORT_SPARK",     _Defaults.PORT_SPARK)
    PORT_RAY_DASH   = _get("PORT_RAY_DASH",  _Defaults.PORT_RAY_DASH)
    PORT_RAY        = _get("PORT_RAY",       _Defaults.PORT_RAY)
    PORT_PORTAINER  = _get("PORT_PORTAINER", _Defaults.PORT_PORTAINER)
    PORT_TTYD       = _get("PORT_TTYD",      _Defaults.PORT_TTYD)

    # ─── Legacy: usuarios del panel (se migran a credentials.enc) ─
    # Se mantiene por compatibilidad pero ya no se usa como fuente
    # principal. Ver credentials.py para la fuente real.
    USUARIOS = {}

    # ─── Herramientas por categoría (checklist de software) ────
    HERRAMIENTAS = {
        "Compiladores":  ["gcc", "g++", "clang", "cmake", "make"],
        "Lenguajes":     ["python3", "java", "go", "rustc", "node", "R"],
        "Python/CI":     ["jupyter", "conda", "pip3"],
        "Paralelo":      ["mpirun", "mpicc", "mpiexec"],
        "Seguridad":     ["nmap", "tcpdump", "tshark", "john", "hashcat",
                          "hydra", "sqlmap"],
        "Redes":         ["iperf3", "mtr", "whois", "mininet"],
        "Contenedores":  ["docker", "apptainer"],
        "Utilidades":    ["git", "tmux", "vim", "htop", "rsync", "jq"],
    }

    # ─── Legacy: NODOS (fuente real es el inventario Ansible) ──
    NODOS = {}
