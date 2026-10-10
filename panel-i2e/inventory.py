"""
Lectura del inventario de Ansible.
Fuente única de verdad: Config.INVENTORY (/home/cluster0/cluster-i2e/hosts)

Cachea el resultado 60s para no invocar ansible-inventory en cada request.
"""
import json
import subprocess
import time
from config import Config

_CACHE = {"data": None, "ts": 0}
_CACHE_TTL = 60  # segundos


def _run_ansible_inventory():
    cmd = ["ansible-inventory", "-i", Config.INVENTORY, "--list"]
    res = subprocess.run(cmd, capture_output=True, text=True,
                         timeout=15, cwd=Config.ANSIBLE_DIR)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "ansible-inventory falló")
    return json.loads(res.stdout)


def _cargar_sin_cache():
    raw = _run_ansible_inventory()
    hostvars = raw.get("_meta", {}).get("hostvars", {})

    grupos = {}
    hosts = {}

    for nombre, data in raw.items():
        if nombre in ("_meta", "all", "ungrouped"):
            continue
        if not isinstance(data, dict):
            continue
        g = {
            "hosts": list(data.get("hosts", [])),
            "children": list(data.get("children", [])),
            "vars": {k: v for k, v in data.items()
                     if k not in ("hosts", "children")},
        }
        grupos[nombre] = g
        for h in g["hosts"]:
            hosts.setdefault(h, {"grupos": [], "vars": {}})
            hosts[h]["grupos"].append(nombre)

    for h, info in hosts.items():
        info["vars"] = hostvars.get(h, {})

    return {"grupos": grupos, "hosts": hosts}


def cargar_inventario(force=False):
    ahora = time.time()
    if force or _CACHE["data"] is None or (ahora - _CACHE["ts"]) > _CACHE_TTL:
        _CACHE["data"] = _cargar_sin_cache()
        _CACHE["ts"] = ahora
    return _CACHE["data"]


def hosts_de_grupo(nombre, _visitados=None):
    """Expande children recursivamente y devuelve IPs únicas ordenadas."""
    inv = cargar_inventario()
    if _visitados is None:
        _visitados = set()
    if nombre in _visitados:
        return []
    _visitados.add(nombre)

    g = inv["grupos"].get(nombre)
    if g:
        resultado = list(g["hosts"])
        for child in g["children"]:
            resultado.extend(hosts_de_grupo(child, _visitados))
        return sorted(set(resultado), key=_ip_key)
    if nombre in inv["hosts"]:
        return [nombre]
    return []


def _ip_key(ip):
    try:
        return [int(p) for p in ip.split(".")]
    except Exception:
        return [0, 0, 0, 0]


def resumen_nodos():
    """
    Lista lista para el panel:
    [{"ip", "nombre", "rol", "grupos", "usuario"}, ...]
    """
    inv = cargar_inventario()
    grupos = inv["grupos"]
    hosts = inv["hosts"]

    compute_sorted = sorted(grupos.get("compute", {}).get("hosts", []),
                            key=_ip_key)
    compute_idx = {ip: i + 1 for i, ip in enumerate(compute_sorted)}

    out = []
    for ip in sorted(hosts.keys(), key=_ip_key):
        info = hosts[ip]
        vars_ = info.get("vars", {})
        gs = info["grupos"]

        nombre = vars_.get("panel_nombre")
        if not nombre:
            if "manager" in gs:
                nombre = "Manager"
            elif "nas" in gs:
                nombre = "NAS"
            elif "compute" in gs:
                nombre = f"Worker {compute_idx.get(ip, '?')}"
            else:
                nombre = ip

        if "manager" in gs:
            rol = "manager"
        elif "nas" in gs:
            rol = "nas"
        elif "compute" in gs:
            rol = "worker"
        else:
            rol = "otros"

        out.append({
            "ip": ip,
            "nombre": nombre,
            "rol": rol,
            "grupos": gs,
            "usuario": vars_.get("ansible_user", ""),
        })
    return out


def es_ip_valida(ip):
    """True si la IP existe en el inventario actual."""
    return ip in cargar_inventario()["hosts"]
