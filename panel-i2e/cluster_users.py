"""
Gestión de usuarios del clúster (Linux + YAML).

- Lee /etc/passwd (usuarios en el rango UID 20000-49999)
- Lee/escribe users.yaml
- Fusiona ambas fuentes y detecta discrepancias

NO confundir con credentials.py (cuentas del panel de login).
"""
import re
import pwd
import yaml
from datetime import datetime
from pathlib import Path

from config import Config

YAML_PATH = Path(Config.USERS_YAML)

# Rango de UIDs que consideramos "usuarios del clúster"
UID_MIN = 20000
UID_MAX = 49999

ROLES = ("professor", "student", "guest")

# Rango de UID por rol
RANGOS = {
    "professor": (20000, 29999),
    "student":   (30000, 39999),
    "guest":     (40000, 49999),
}


# ─── YAML ─────────────────────────────────────────────────────
def leer_yaml():
    if not YAML_PATH.exists():
        return {"users": [], "config": {}}
    try:
        with open(YAML_PATH) as f:
            data = yaml.safe_load(f) or {}
        if "users" not in data:
            data["users"] = []
        if "config" not in data:
            data["config"] = {}
        return data
    except Exception as e:
        return {"users": [], "config": {}, "error": str(e)}


def guardar_yaml(data):
    YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(YAML_PATH, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False,
                       sort_keys=False, allow_unicode=True)


# ─── Sistema ──────────────────────────────────────────────────
def usuarios_sistema():
    """Lee /etc/passwd y devuelve los del rango de clúster."""
    resultado = []
    for p in pwd.getpwall():
        if UID_MIN <= p.pw_uid <= UID_MAX:
            resultado.append({
                "username": p.pw_name,
                "uid":      p.pw_uid,
                "gid":      p.pw_gid,
                "fullname": (p.pw_gecos or "").split(",")[0] or p.pw_name,
                "home":     p.pw_dir,
                "shell":    p.pw_shell,
            })
    resultado.sort(key=lambda u: u["uid"])
    return resultado


def existe_en_sistema(username):
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


# ─── Fusión ───────────────────────────────────────────────────
def _rol_por_uid(uid):
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return "guest"
    for rol, (a, b) in RANGOS.items():
        if a <= uid <= b:
            return rol
    return "guest"


def listar_combinado():
    """
    Devuelve TODOS los usuarios conocidos, con banderas de dónde están.
    Fusiona YAML y /etc/passwd.
    """
    data = leer_yaml()
    yaml_users = {u["username"]: u for u in data.get("users", [])
                  if u.get("username")}
    sis_users = {u["username"]: u for u in usuarios_sistema()}

    todos = set(yaml_users) | set(sis_users)
    out = []

    for username in sorted(todos, key=lambda u: (
        sis_users.get(u, {}).get("uid") or yaml_users.get(u, {}).get("uid") or 0,
        u
    )):
        en_yaml = username in yaml_users
        en_sis  = username in sis_users

        base = dict(yaml_users.get(username) or sis_users.get(username) or {})
        item = {
            "username": username,
            "fullname": base.get("fullname") or base.get("name") or username,
            "uid":      base.get("uid"),
            "role":     base.get("role") or _rol_por_uid(base.get("uid")),
            "active":   base.get("active", True),
            "expires":  base.get("expires"),
            "created":  base.get("created"),
            "shell":    base.get("shell", "/bin/bash"),
            "home":     base.get("home", ""),
            "en_yaml":    en_yaml,
            "en_sistema": en_sis,
        }

        if en_sis:
            s = sis_users[username]
            item["uid"]  = s["uid"]
            item["shell"] = s["shell"]
            item["home"]  = s["home"]
            if not item["fullname"]:
                item["fullname"] = s["fullname"]

        if en_yaml and en_sis:
            item["estado"] = "ok"
        elif en_yaml and not en_sis:
            item["estado"] = "pendiente_aplicar"
            item["aviso"]  = "En YAML, aún no en el sistema — pulsa «Aplicar al sistema»"
        else:
            item["estado"] = "pendiente_importar"
            item["aviso"]  = "En el sistema, no está en el YAML — pulsa «Importar del sistema»"

        out.append(item)

    return {"users": out, "config": data.get("config", {})}


# ─── Operaciones ──────────────────────────────────────────────
def validar_username(u):
    return bool(re.fullmatch(r"[a-z][a-z0-9._-]{2,31}", u or ""))


def validar_uid(uid):
    try:
        uid = int(uid)
        return UID_MIN <= uid <= UID_MAX
    except (TypeError, ValueError):
        return False


def siguiente_uid(role):
    if role not in RANGOS:
        role = "guest"
    a, b = RANGOS[role]
    data = leer_yaml()
    usados = [u.get("uid", 0) for u in data.get("users", [])
              if isinstance(u.get("uid"), int) and a <= u["uid"] <= b]
    return (max(usados) + 1) if usados else (a + 1)


def crear(username, fullname, role, uid=None, expires=None):
    if not validar_username(username):
        raise ValueError("Username inválido (a-z, 0-9, ., -, _; min 3)")
    if role not in ROLES:
        raise ValueError(f"Rol inválido: {role}")
    data = leer_yaml()
    if any(u.get("username") == username for u in data["users"]):
        raise ValueError(f"{username} ya existe en el YAML")
    if existe_en_sistema(username):
        raise ValueError(f"{username} ya existe en el sistema")

    uid = int(uid) if uid else siguiente_uid(role)
    if not validar_uid(uid):
        raise ValueError(f"UID fuera del rango {UID_MIN}-{UID_MAX}")

    nuevo = {
        "username": username,
        "fullname": fullname or username,
        "uid":      uid,
        "role":     role,
        "active":   True,
        "created":  datetime.now().strftime("%Y-%m-%d"),
        "shell":    "/bin/bash",
    }
    if expires:
        nuevo["expires"] = str(expires)
    data["users"].append(nuevo)
    guardar_yaml(data)
    return nuevo


def editar(username, cambios):
    data = leer_yaml()
    encontrado = None
    for u in data["users"]:
        if u.get("username") == username:
            encontrado = u
            break
    if not encontrado:
        # Crear entrada mínima si solo estaba en sistema
        sis = next((s for s in usuarios_sistema() if s["username"] == username), None)
        if not sis:
            raise ValueError(f"{username} no existe")
        encontrado = {
            "username": username,
            "fullname": sis["fullname"],
            "uid":      sis["uid"],
            "role":     _rol_por_uid(sis["uid"]),
            "active":   True,
            "created":  datetime.now().strftime("%Y-%m-%d"),
        }
        data["users"].append(encontrado)

    for k in ("fullname", "uid", "role", "active", "expires", "shell"):
        if k in cambios:
            v = cambios[k]
            if k == "uid":
                v = int(v)
                if not validar_uid(v):
                    raise ValueError(f"UID fuera de rango: {v}")
            if k == "role" and v not in ROLES:
                raise ValueError(f"Rol inválido: {v}")
            encontrado[k] = v

    guardar_yaml(data)
    return encontrado


def eliminar_del_yaml(username):
    data = leer_yaml()
    antes = len(data["users"])
    data["users"] = [u for u in data["users"] if u.get("username") != username]
    if len(data["users"]) == antes:
        return False
    guardar_yaml(data)
    return True


def importar_del_sistema():
    """Añade al YAML los usuarios del sistema que no estén ya."""
    data = leer_yaml()
    existentes = {u["username"] for u in data["users"]}
    añadidos = []
    for s in usuarios_sistema():
        if s["username"] in existentes:
            continue
        data["users"].append({
            "username": s["username"],
            "fullname": s["fullname"],
            "uid":      s["uid"],
            "role":     _rol_por_uid(s["uid"]),
            "active":   True,
            "created":  datetime.now().strftime("%Y-%m-%d"),
            "shell":    s["shell"],
        })
        añadidos.append(s["username"])
    if añadidos:
        guardar_yaml(data)
    return añadidos


def resumen():
    combo = listar_combinado()
    users = combo["users"]
    return {
        "total":       len(users),
        "en_sistema":  sum(1 for u in users if u["en_sistema"]),
        "en_yaml":     sum(1 for u in users if u["en_yaml"]),
        "activos":     sum(1 for u in users if u.get("active", True)),
        "professors":  sum(1 for u in users if u.get("role") == "professor"),
        "students":    sum(1 for u in users if u.get("role") == "student"),
        "guests":      sum(1 for u in users if u.get("role") == "guest"),
        "discrepancias": sum(1 for u in users if u["estado"] != "ok"),
    }
