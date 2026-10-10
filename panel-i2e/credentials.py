"""
Credenciales del panel.

Estrategia:
1. Cuentas del PANEL (admin, etc.):
   - origen="panel", hash local en credentials.enc

2. Usuarios del CLÚSTER (Linux UID 20000-49999):
   - hash local en credentials.enc con origen="cluster" (fallback)
   - el rol del panel se recalcula SIEMPRE desde users.yaml:
        professor → operator
        student   → student
        guest     → viewer

3. Cualquier otro usuario del sistema con PAM disponible:
   - intenta PAM como último recurso
"""
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash

from config import Config

try:
    import pam as _pam
    PAM_DISPONIBLE = True
except Exception:
    PAM_DISPONIBLE = False


DATA_DIR = Path(Config.DATA_DIR)
MASTER_KEY_FILE = DATA_DIR / "master.key"
CREDS_FILE = DATA_DIR / "credentials.enc"


# ─── Cifrado ─────────────────────────────────────────────────
def _load_or_create_master_key() -> bytes:
    DATA_DIR.mkdir(exist_ok=True)
    if MASTER_KEY_FILE.exists():
        return MASTER_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    MASTER_KEY_FILE.write_bytes(key)
    os.chmod(MASTER_KEY_FILE, 0o600)
    return key


def _get_fernet() -> Fernet:
    return Fernet(_load_or_create_master_key())


def _load_creds() -> dict:
    if not CREDS_FILE.exists():
        return {}
    try:
        return json.loads(_get_fernet().decrypt(CREDS_FILE.read_bytes()))
    except (InvalidToken, json.JSONDecodeError):
        return {}


def _save_creds(data: dict):
    cifrado = _get_fernet().encrypt(json.dumps(data).encode())
    CREDS_FILE.write_bytes(cifrado)
    os.chmod(CREDS_FILE, 0o600)


# ─── PAM ─────────────────────────────────────────────────────
def _verificar_pam(usuario: str, password: str) -> bool:
    if not PAM_DISPONIBLE:
        return False
    if not usuario or not password:
        return False
    try:
        p = _pam.pam()
        p.start("login", usuario)
        p.authenticate()
        p.acct_mgmt()
        return True
    except Exception:
        return False


def _info_cluster(usuario: str) -> dict | None:
    try:
        import cluster_users
        for u in cluster_users.listar_combinado().get("users", []):
            if u.get("username") == usuario:
                return u
    except Exception:
        pass
    return None


def _rol_panel_desde_cluster(cluster_role: str) -> str:
    return {
        "professor": "operator",
        "student":   "student",
        "guest":     "viewer",
    }.get(cluster_role, "viewer")


# ─── API pública ─────────────────────────────────────────────
def init_default_admin(username=None, password=None):
    # Cargar valores desde Config si no se pasan explícitamente
    if username is None or password is None:
        try:
            from config import Config
            username = username or getattr(Config, 'ADMIN_USER', 'Cluster0')
            password = password or getattr(Config, 'ADMIN_PASSWORD', 'oxoCluster0')
        except Exception:
            username = username or 'Cluster0'
            password = password or 'oxoCluster0'
    
    creds = _load_creds()
    if creds:
        return False
    creds[username] = {
        "hash": generate_password_hash(password),
        "role": "admin",
        "nombre": "Administrador Principal",
        "origen": "panel",
    }
    _save_creds(creds)
    return True


def verificar(usuario: str, password: str) -> dict | None:
    """
    Orden:
    1. credentials.enc (si está)
       - origen="panel":  hash local + rol guardado
       - origen="cluster": hash local + rol recalculado desde users.yaml
    2. PAM (último recurso para usuarios del sistema)
    """
    if not usuario or not password:
        return None

    # 1) credentials.enc
    creds = _load_creds()
    info = creds.get(usuario)
    if info:
        if check_password_hash(info.get("hash", ""), password):
            origen = info.get("origen", "panel")
            if origen == "cluster":
                cluster = _info_cluster(usuario) or {}
                return {
                    "usuario": usuario,
                    "role":    _rol_panel_desde_cluster(cluster.get("role", "guest")),
                    "nombre":  cluster.get("fullname", info.get("nombre", usuario)),
                    "origen":  "cluster",
                }
            return {
                "usuario": usuario,
                "role":    info.get("role", "viewer"),
                "nombre":  info.get("nombre", usuario),
                "origen":  "panel",
            }
        return None

    # 2) PAM
    if _verificar_pam(usuario, password):
        cluster = _info_cluster(usuario) or {}
        return {
            "usuario": usuario,
            "role":    _rol_panel_desde_cluster(cluster.get("role", "guest")),
            "nombre":  cluster.get("fullname", usuario),
            "origen":  "cluster",
        }

    return None


def tiene_hash(usuario: str) -> bool:
    """True solo si el usuario tiene una entrada en credentials.enc."""
    return usuario in _load_creds()


def obtener_usuario(usuario: str) -> dict | None:
    """Info del usuario. Si es del clúster recalcula rol desde users.yaml."""
    creds = _load_creds()
    info = creds.get(usuario)
    if info:
        origen = info.get("origen", "panel")
        if origen == "cluster":
            cluster = _info_cluster(usuario) or {}
            return {
                "usuario": usuario,
                "role":    _rol_panel_desde_cluster(cluster.get("role", "guest")),
                "nombre":  cluster.get("fullname", info.get("nombre", usuario)),
                "origen":  "cluster",
            }
        return {
            "usuario": usuario,
            "role":    info.get("role", "viewer"),
            "nombre":  info.get("nombre", usuario),
            "origen":  "panel",
        }
    # No está en creds: mirar users.yaml
    cluster = _info_cluster(usuario)
    if cluster:
        return {
            "usuario": usuario,
            "role":    _rol_panel_desde_cluster(cluster.get("role", "guest")),
            "nombre":  cluster.get("fullname", usuario),
            "origen":  "cluster_sin_hash",
        }
    return None


def listar_usuarios() -> dict:
    """Solo cuentas locales del panel (excluye usuarios del clúster)."""
    creds = _load_creds()
    return {
        u: {"role": info.get("role"), "nombre": info.get("nombre"),
            "origen": info.get("origen", "panel")}
        for u, info in creds.items()
        if info.get("origen", "panel") == "panel"
    }


def crear_usuario(usuario: str, password: str, role: str, nombre: str = "",
                  origen: str = "panel"):
    ROLES_VALIDOS = ("viewer", "student", "operator", "admin")
    if role not in ROLES_VALIDOS:
        raise ValueError(f"Rol inválido: {role}")
    creds = _load_creds()
    creds[usuario] = {
        "hash": generate_password_hash(password),
        "role": role,
        "nombre": nombre or usuario,
        "origen": origen,
    }
    _save_creds(creds)


def cambiar_password(usuario: str, nueva: str) -> bool:
    creds = _load_creds()
    if usuario not in creds:
        return False
    creds[usuario]["hash"] = generate_password_hash(nueva)
    _save_creds(creds)
    return True


def eliminar_usuario(usuario: str) -> bool:
    creds = _load_creds()
    if usuario not in creds:
        return False
    del creds[usuario]
    _save_creds(creds)
    return True


def exportar_backup() -> dict:
    return _load_creds()


def importar_backup(data: dict):
    _save_creds(data)
