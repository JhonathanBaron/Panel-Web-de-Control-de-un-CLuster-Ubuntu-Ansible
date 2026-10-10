"""
Configuración editable del panel.

Dos archivos JSON que el admin modifica desde la UI:
  · data/herramientas.json  → checklist de diagnóstico (command -v)
  · data/apps.json          → panel de control de servicios

Si no existen, se crean con valores por defecto derivados de config.py.
Un clúster nuevo arranca funcionando sin configuración manual.
"""
import json
import re
from pathlib import Path

from config import Config

_DATA         = Path(Config.DATA_DIR)
_HERRAMIENTAS = _DATA / "herramientas.json"
_APPS         = _DATA / "apps.json"


# ─── Utilidad común ──────────────────────────────────────────
def _guardar_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════
# HERRAMIENTAS — checklist de diagnóstico
# ══════════════════════════════════════════════════════════════
def _herramientas_default() -> dict:
    return {
        "categorias": [
            {"nombre": k, "herramientas": list(v)}
            for k, v in Config.HERRAMIENTAS.items()
        ]
    }


def leer_herramientas() -> dict:
    if not _HERRAMIENTAS.exists():
        _guardar_json(_HERRAMIENTAS, _herramientas_default())
    try:
        data = json.loads(_HERRAMIENTAS.read_text())
        if not isinstance(data, dict) or "categorias" not in data:
            raise ValueError("estructura inválida")
        if not isinstance(data["categorias"], list):
            raise ValueError("'categorias' debe ser lista")
        return data
    except Exception as e:
        print(f"[apps_config] herramientas.json inválido ({e}), usando defaults")
        return _herramientas_default()


def guardar_herramientas(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("cuerpo debe ser objeto JSON")
    cats = data.get("categorias")
    if not isinstance(cats, list):
        raise ValueError("'categorias' debe ser lista")

    vistas = set()
    for i, cat in enumerate(cats):
        if not isinstance(cat, dict):
            raise ValueError(f"categoría #{i}: debe ser objeto")
        nombre = str(cat.get("nombre", "")).strip()
        if not nombre:
            raise ValueError(f"categoría #{i}: falta nombre")
        if len(nombre) > 60:
            raise ValueError(f"categoría '{nombre}': nombre demasiado largo")
        if nombre in vistas:
            raise ValueError(f"categoría duplicada: '{nombre}'")
        vistas.add(nombre)

        hs = cat.get("herramientas", [])
        if not isinstance(hs, list):
            raise ValueError(f"categoría '{nombre}': 'herramientas' debe ser lista")
        for h in hs:
            if not isinstance(h, str) or not re.fullmatch(r"[a-zA-Z0-9_.+-]+", h):
                raise ValueError(f"herramienta inválida en '{nombre}': {h!r}")

    _guardar_json(_HERRAMIENTAS, data)
    return data


# ══════════════════════════════════════════════════════════════
# APPS — panel de control de servicios
# ══════════════════════════════════════════════════════════════
def _apps_default() -> dict:
    return {
        "apps": [
            {
                "id": "spark", "nombre": "Spark", "icono": "⚡",
                "host": "10.4.8.10", "puerto": Config.PORT_SPARK_UI,
                "proto": "http",
                "check":     {"tipo": "url", "valor": "/"},
                "start":     {"tipo": "playbook", "valor": "19_spark_start.yml"},
                "stop":      {"tipo": "playbook", "valor": "19_spark_stop.yml"},
                "uninstall": {"tipo": "playbook", "valor": "19_spark_uninstall.yml"},
                "descripcion": "Motor de procesamiento distribuido",
            },
            {
                "id": "ray", "nombre": "Ray", "icono": "☀️",
                "host": "10.4.8.10", "puerto": Config.PORT_RAY_DASH,
                "proto": "http",
                "check": {"tipo": "cmd",
                          "valor": "/srv/nas/tools/miniforge/envs/ray/bin/ray status --address=10.4.8.10:6380"},
                "start":     {"tipo": "playbook", "valor": "18_ray.yml"},
                "stop":      {"tipo": "systemd", "valor": "none"},
                "uninstall": {"tipo": "playbook", "valor": "18_ray_uninstall.yml"},
                "descripcion": "Framework de cómputo distribuido",
            },
            {
                "id": "jupyter", "nombre": "JupyterHub", "icono": "📓",
                "host": "10.4.8.10", "puerto": Config.PORT_JUPYTER,
                "proto": "http",
                "check": {"tipo": "url", "valor": "/hub/login"},
                "start": {"tipo": "systemd", "valor": "jupyterhub"},
                "stop":  {"tipo": "systemd", "valor": "jupyterhub"},
                "uninstall": {"tipo": "playbook", "valor": "17_jupyterhub_uninstall.yml"},
                "descripcion": "Cuadernos interactivos multi-usuario",
            },
            {
                "id": "portainer", "nombre": "Portainer", "icono": "🐳",
                "host": "10.4.8.10", "puerto": Config.PORT_PORTAINER,
                "proto": "https",
                "check": {"tipo": "url", "valor": "/"},
                "start": None, "stop": None, "uninstall": None,
                "descripcion": "Gestión visual de contenedores Docker",
            },
        ]
    }


_APP_KEYS_OPC = ("start", "stop", "uninstall")


def leer_apps() -> dict:
    if not _APPS.exists():
        _guardar_json(_APPS, _apps_default())
    try:
        data = json.loads(_APPS.read_text())
        if not isinstance(data, dict) or "apps" not in data:
            raise ValueError("estructura inválida")
        if not isinstance(data["apps"], list):
            raise ValueError("'apps' debe ser lista")
        return data
    except Exception as e:
        print(f"[apps_config] apps.json inválido ({e}), usando defaults")
        return _apps_default()


def _validar_accion(app_id: str, key: str, cfg) -> None:
    if cfg is None:
        return
    if not isinstance(cfg, dict):
        raise ValueError(f"{app_id}: '{key}' debe ser objeto o null")
    tipo  = cfg.get("tipo")
    valor = str(cfg.get("valor", "")).strip()
    if tipo not in ("playbook", "systemd"):
        raise ValueError(f"{app_id}: {key}.tipo debe ser 'playbook' o 'systemd'")
    if not valor:
        raise ValueError(f"{app_id}: {key}.valor vacío")
    if key == "uninstall" and tipo != "playbook":
        raise ValueError(f"{app_id}: 'uninstall' solo admite tipo 'playbook'")


def guardar_apps(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("cuerpo debe ser objeto JSON")
    apps = data.get("apps")
    if not isinstance(apps, list):
        raise ValueError("'apps' debe ser lista")

    ids = set()
    for i, app in enumerate(apps):
        if not isinstance(app, dict):
            raise ValueError(f"app #{i}: debe ser objeto")
        app_id = str(app.get("id", "")).strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9-]*", app_id):
            raise ValueError(f"app #{i}: id inválido '{app_id}' "
                             "(solo a-z, 0-9, '-', empezando por letra)")
        if app_id in ids:
            raise ValueError(f"id duplicado: '{app_id}'")
        ids.add(app_id)
        app["id"] = app_id

        if not str(app.get("nombre", "")).strip():
            raise ValueError(f"app '{app_id}': falta nombre")
        if not str(app.get("host", "")).strip():
            raise ValueError(f"app '{app_id}': falta host")

        try:
            puerto = int(app.get("puerto", 0))
            if not (1 <= puerto <= 65535):
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"app '{app_id}': puerto inválido")

        if app.get("proto", "http") not in ("http", "https"):
            raise ValueError(f"app '{app_id}': proto debe ser http o https")

        check = app.get("check", {})
        if not isinstance(check, dict):
            raise ValueError(f"app '{app_id}': 'check' debe ser objeto")
        if check.get("tipo") not in ("url", "cmd"):
            raise ValueError(f"app '{app_id}': check.tipo debe ser 'url' o 'cmd'")
        if not str(check.get("valor", "")).strip():
            raise ValueError(f"app '{app_id}': check.valor vacío")

        for k in _APP_KEYS_OPC:
            _validar_accion(app_id, k, app.get(k))

    _guardar_json(_APPS, data)
    return data
