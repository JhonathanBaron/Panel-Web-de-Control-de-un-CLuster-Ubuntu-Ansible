"""
Config de nodos: MAC, WOL, nombres visibles.
Persiste en data/nodes.json.
"""
import json
import re
import socket
from pathlib import Path
from config import Config

_FILE = Path(Config.DATA_DIR) / "nodes.json"


def _leer():
    if not _FILE.exists():
        return {}
    try:
        return json.loads(_FILE.read_text())
    except Exception:
        return {}


def _guardar(data):
    _FILE.parent.mkdir(exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def todos():
    return _leer()


def obtener(ip):
    return _leer().get(ip, {})


def actualizar(ip, cambios):
    data = _leer()
    if ip not in data:
        data[ip] = {}
    for k in ("nombre", "mac", "wol"):
        if k in cambios:
            data[ip][k] = cambios[k]
    _guardar(data)
    return data[ip]


def _normalizar_mac(mac):
    if not mac:
        return ""
    mac = mac.strip().lower().replace("-", ":").replace(".", "")
    mac = re.sub(r"[^0-9a-f:]", "", mac)
    if ":" not in mac and len(mac) == 12:
        mac = ":".join(mac[i:i+2] for i in range(0, 12, 2))
    if not re.fullmatch(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}", mac):
        raise ValueError("MAC inválida")
    return mac


def validar_mac(mac):
    try:
        return _normalizar_mac(mac)
    except ValueError:
        return None


def _magic_packet(mac):
    mac_bytes = bytes.fromhex(mac.replace(":", ""))
    return b"\xff" * 6 + mac_bytes * 16


def _broadcast_de(ip):
    """Calcula la dirección de broadcast de la subred del nodo destino."""
    try:
        partes = ip.split('.')
        if len(partes) == 4:
            return '.'.join(partes[:3]) + '.255'
    except Exception:
        pass
    return '255.255.255.255'


def enviar_wol(ip, mac=None, port=9, timeout=1.5):
    """Envía un magic packet. No bloquea más de `timeout` segundos."""
    if mac is None:
        mac = obtener(ip).get("mac", "")
    mac = _normalizar_mac(mac)
    if not mac:
        raise ValueError(ip + ": sin MAC configurada")

    pkt = _magic_packet(mac)

    # Probar varias direcciones de broadcast para máxima compatibilidad
    destinos = [
        ('255.255.255.255', port),
        (_broadcast_de(ip), port),
        (ip, port),                    # unicast como último recurso
    ]

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)              # ← clave: evita bloqueos
    enviados = 0
    ultimo_error = None
    try:
        for destino, p in destinos:
            try:
                s.sendto(pkt, (destino, p))
                enviados += 1
            except OSError as e:
                ultimo_error = e
                continue
    finally:
        s.close()

    if enviados == 0:
        raise RuntimeError(
            f"No se pudo enviar WOL a {ip}: {ultimo_error}")

    return mac
