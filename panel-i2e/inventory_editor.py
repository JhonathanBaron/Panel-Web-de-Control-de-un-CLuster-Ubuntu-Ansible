"""
Gestor del inventario de Ansible.

Trabaja directamente sobre el archivo /home/cluster0/cluster-i2e/hosts
preservando comentarios y estructura. Antes de cada guardado, hace backup.

Formato soportado:
    [grupo]                 → hosts con vars inline
    [grupo:children]        → subgrupos
    [grupo:vars]            → variables del grupo
    [all:vars]              → variables globales
"""
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from config import Config

INVENTORY_PATH = Path(Config.INVENTORY)
BACKUP_DIR     = Path(Config.DATA_DIR) / "inventory-backups"
MAX_BACKUPS    = 30

# ─── Nombres válidos ────────────────────────────────────────
_RE_GRUPO  = re.compile(r'^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$')
_RE_IP     = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')
_RE_HOST   = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$')
_RE_VAR    = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


# ─── Utilidades ─────────────────────────────────────────────
def _ip_valida(ip):
    if not _RE_IP.match(ip or ""):
        return False
    return all(0 <= int(p) <= 255 for p in ip.split("."))


def _nombre_grupo_valido(n):
    return bool(_RE_GRUPO.match(n or ""))


def _nombre_host_valido(n):
    return bool(_RE_HOST.match(n or ""))


# ─── Lectura / escritura ────────────────────────────────────
def leer_raw():
    if not INVENTORY_PATH.exists():
        return ""
    return INVENTORY_PATH.read_text()


def guardar_raw(text, usuario=None):
    """Guarda el inventario haciendo backup previo."""
    if not INVENTORY_PATH.exists():
        raise FileNotFoundError(str(INVENTORY_PATH))

    # 1) Backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bkp = BACKUP_DIR / f"hosts-{ts}.ini"
    shutil.copy2(str(INVENTORY_PATH), str(bkp))

    # Limitar backups
    backups = sorted(BACKUP_DIR.glob("hosts-*.ini"))
    for old in backups[:-MAX_BACKUPS]:
        try: old.unlink()
        except Exception: pass

    # 2) Escribir nuevo
    original_mode = INVENTORY_PATH.stat().st_mode
    INVENTORY_PATH.write_text(text)
    try: INVENTORY_PATH.chmod(original_mode)
    except Exception: pass

    # 3) Invalidar cache de inventory.py para que se recargue
    try:
        import inventory
        inventory.cargar_inventario(force=True)
    except Exception:
        pass

    return bkp.name


# ─── Parseo ─────────────────────────────────────────────────
def parsear(text):
    """Devuelve estructura ordenada del inventario."""
    lineas = text.split("\n")
    grupos = {}   # nombre → {tipo, hosts:[], children:[], vars:{}}
    orden = []
    actual = None

    for l in lineas:
        ls = l.strip()
        m = re.match(r'^\[([^\]]+)\]\s*$', ls)
        if m:
            nombre_raw = m.group(1).strip()
            if ":" in nombre_raw:
                base, tipo = nombre_raw.split(":", 1)
                nombre = base.strip()
                tipo = tipo.strip().lower()
            else:
                nombre = nombre_raw
                tipo = "normal"
            if nombre not in grupos:
                grupos[nombre] = {"tipo": tipo, "hosts": [],
                                  "children": [], "vars": {}}
                orden.append(nombre)
            actual = nombre
            continue
        if actual is None:
            continue
        if not ls or ls.startswith("#") or ls.startswith(";"):
            continue

        g = grupos[actual]
        if g["tipo"] == "children":
            if _nombre_grupo_valido(ls):
                g["children"].append(ls)
            continue
        if g["tipo"] == "vars":
            if "=" in ls:
                k, v = ls.split("=", 1)
                g["vars"][k.strip()] = v.strip()
            continue
        # normal: host con vars opcionales
        partes = ls.split()
        if not partes:
            continue
        ip = partes[0]
        vars_ = {}
        for p in partes[1:]:
            if "=" in p:
                k, v = p.split("=", 1)
                vars_[k] = v
        g["hosts"].append({"ip": ip, "vars": vars_})

    return {"grupos": grupos, "orden": orden}


# ─── Validación ─────────────────────────────────────────────
def validar(text):
    """Valida el inventario. Devuelve (ok, lista_errores, lista_warnings)."""
    errores = []
    warnings = []
    try:
        parsed = parsear(text)
    except Exception as e:
        return False, [f"Error parseando: {e}"], []

    grupos = parsed["grupos"]
    ips_vistas = {}
    hosts_definidos = set()
    grupos_definidos = set(grupos.keys())

    for nombre, g in grupos.items():
        if not _nombre_grupo_valido(nombre):
            errores.append(f"Nombre de grupo inválido: '{nombre}'")

        # Validar hosts
        for h in g.get("hosts", []):
            ip = h["ip"]
            if not (_ip_valida(ip) or _nombre_host_valido(ip)):
                errores.append(f"[{nombre}] Host inválido: '{ip}'")
            if ip in ips_vistas and ips_vistas[ip] != nombre:
                warnings.append(f"{ip} aparece en varios grupos: "
                                f"[{ips_vistas[ip]}] y [{nombre}]")
            elif ip not in ips_vistas:
                ips_vistas[ip] = nombre
            hosts_definidos.add(ip)

            for k in h["vars"].keys():
                if not _RE_VAR.match(k):
                    errores.append(f"[{nombre}] Variable inválida en {ip}: '{k}'")

        # Validar children
        for c in g.get("children", []):
            if c not in grupos_definidos:
                errores.append(f"[{nombre}:children] referencia a grupo inexistente: '{c}'")

        # Validar vars
        for k in g.get("vars", {}).keys():
            if not _RE_VAR.match(k):
                errores.append(f"[{nombre}:vars] Variable inválida: '{k}'")

    if not hosts_definidos:
        warnings.append("El inventario no define ningún host")

    return (len(errores) == 0), errores, warnings


# ─── Operaciones sobre hosts ────────────────────────────────
def _linea_host(ip, vars_dict):
    partes = [ip]
    for k, v in vars_dict.items():
        if v is None or v == "":
            continue
        # Citar si tiene espacios
        if " " in str(v):
            v = f'"{v}"'
        partes.append(f"{k}={v}")
    return " ".join(partes)


def añadir_nodo(text, ip, grupos, vars_dict):
    """Añade `ip` a cada grupo de `grupos` (lista)."""
    if not (_ip_valida(ip) or _nombre_host_valido(ip)):
        raise ValueError(f"IP/host inválido: {ip}")
    if not grupos:
        raise ValueError("Debes indicar al menos un grupo")

    parsed = parsear(text)
    existentes = set()
    for g in parsed["grupos"].values():
        for h in g.get("hosts", []):
            existentes.add(h["ip"])
    if ip in existentes:
        raise ValueError(f"{ip} ya existe en el inventario")

    lineas = text.split("\n")
    for grupo in grupos:
        if grupo not in parsed["grupos"]:
            raise ValueError(f"Grupo inexistente: [{grupo}]")

        # Encontrar cabecera [grupo]
        patron_ini = re.compile(r'^\s*\[' + re.escape(grupo) + r'\]\s*$')
        patron_sec = re.compile(r'^\s*\[[^\]]+\]\s*$')
        ini = None
        for i, l in enumerate(lineas):
            if patron_ini.match(l):
                ini = i
                break
        if ini is None:
            raise ValueError(f"No se pudo encontrar [{grupo}]")

        # Fin de sección
        fin = len(lineas)
        for j in range(ini + 1, len(lineas)):
            if patron_sec.match(lineas[j]):
                fin = j
                break

        # Última línea útil
        ultima = ini
        for j in range(ini + 1, fin):
            if lineas[j].strip():
                ultima = j

        # Insertar
        lineas.insert(ultima + 1, _linea_host(ip, vars_dict))

    return "\n".join(lineas)


def eliminar_nodo(text, ip):
    """Elimina todas las líneas del host `ip` en todos los grupos."""
    lineas = text.split("\n")
    nuevas = []
    eliminadas = 0
    for l in lineas:
        ls = l.strip()
        if ls.startswith("#") or ls.startswith(";"):
            nuevas.append(l); continue
        partes = ls.split()
        if partes and partes[0] == ip:
            eliminadas += 1
            continue
        nuevas.append(l)
    if eliminadas == 0:
        raise ValueError(f"{ip} no encontrado en el inventario")
    return "\n".join(nuevas)


def editar_nodo(text, ip, nuevos_vars, nuevos_grupos=None):
    """
    - Actualiza las vars del host `ip` (todas las líneas donde aparezca).
    - Si se pasa `nuevos_grupos`, mueve el host a esos grupos (elimina de los demás
      grupos normales y añade a los nuevos).
    """
    if not _ip_valida(ip):
        raise ValueError(f"IP inválida: {ip}")

    # 1) Localizar el host
    lineas = text.split("\n")
    encontrado = False
    for l in lineas:
        ls = l.strip()
        if ls.startswith("#") or ls.startswith(";"):
            continue
        partes = ls.split()
        if partes and partes[0] == ip:
            encontrado = True
            break
    if not encontrado:
        raise ValueError(f"{ip} no existe en el inventario")

    # 2) Si cambian grupos, eliminarlo de todos los grupos "normales"
    if nuevos_grupos is not None:
        parsed = parsear(text)
        # Quitar del inventario
        text = eliminar_nodo(text, ip)
        # Añadir a los nuevos grupos
        text = añadir_nodo(text, ip, list(nuevos_grupos), nuevos_vars)
        return text

    # 3) Solo cambiar vars: reemplazar la línea donde aparece
    lineas = text.split("\n")
    nueva_linea_host = _linea_host(ip, nuevos_vars)
    for i, l in enumerate(lineas):
        ls = l.strip()
        if ls.startswith("#") or ls.startswith(";"):
            continue
        partes = ls.split()
        if partes and partes[0] == ip:
            indent = l[:len(l) - len(l.lstrip())]
            lineas[i] = indent + nueva_linea_host
    return "\n".join(lineas)


# ─── Backups ────────────────────────────────────────────────
def listar_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for f in sorted(BACKUP_DIR.glob("hosts-*.ini"), reverse=True):
        try:
            st = f.stat()
            items.append({
                "nombre": f.name,
                "size":   st.st_size,
                "mtime":  datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
        except Exception:
            pass
    return items


def restaurar_backup(nombre):
    if "/" in nombre or ".." in nombre:
        raise ValueError("Nombre de backup inválido")
    src = BACKUP_DIR / nombre
    if not src.is_file():
        raise ValueError("Backup no encontrado")

    # Backup del actual antes de restaurar
    if INVENTORY_PATH.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(str(INVENTORY_PATH), str(BACKUP_DIR / f"hosts-{ts}.ini"))

    shutil.copy2(str(src), str(INVENTORY_PATH))

    try:
        import inventory
        inventory.cargar_inventario(force=True)
    except Exception:
        pass
    return True
