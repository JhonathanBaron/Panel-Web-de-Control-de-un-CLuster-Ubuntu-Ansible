"""
Histórico de métricas de los nodos.
- Guarda 1 muestra por nodo cada MIN_INTERVALO_S segundos
- Mantiene solo MAX_MUESTRAS por nodo en memoria al responder
"""
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from config import Config

_DIR  = Path(Config.DATA_DIR)
_FILE = _DIR / "metrics.jsonl"
_LOCK = threading.Lock()

# ─── Configuración optimizada ────────────────────────────────
MIN_INTERVALO_S = 120       # guardar cada 2 minutos por nodo
MAX_HISTORICO_S = 900       # solo se conservan los últimos 15 min
MAX_MUESTRAS    = 60        # tope duro al responder por API
_MAX_LINEAS     = 8000      # tope del fichero (~5 días de datos)

# Cache en memoria del último timestamp por nodo (evita leer el archivo)
_ultimo_ts = {}


def recordar(ip, cpu_pct=None, ram_pct=None, disk_pct=None, load=None):
    """Añade una muestra solo si pasó el intervalo mínimo desde la última."""
    try:
        ahora = time.time()

        # ¿Toca guardar para este nodo?
        with _LOCK:
            ultimo = _ultimo_ts.get(ip, 0)
            if ahora - ultimo < MIN_INTERVALO_S:
                return False
            _ultimo_ts[ip] = ahora

        _DIR.mkdir(exist_ok=True)
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "ip": ip}
        if cpu_pct  is not None: entry["cpu"]  = round(float(cpu_pct), 1)
        if ram_pct  is not None: entry["ram"]  = round(float(ram_pct), 1)
        if disk_pct is not None: entry["disk"] = round(float(disk_pct), 1)
        if load     is not None: entry["load"] = [round(float(x), 2) for x in load]

        with _LOCK:
            with open(_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Trim muy de vez en cuando, no en cada escritura
            try:
                if _FILE.stat().st_size > 2_000_000:   # >2 MB
                    lineas = _FILE.read_text().splitlines()
                    if len(lineas) > _MAX_LINEAS:
                        _FILE.write_text("\n".join(lineas[-_MAX_LINEAS:]) + "\n")
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"[metrics] recordar: {e}")
        return False


def _leer_recientes(ips_set, max_edad_s=MAX_HISTORICO_S):
    """Lee el archivo y devuelve solo las muestras de los últimos N segundos."""
    resultado = {ip: [] for ip in ips_set}
    if not _FILE.exists():
        return resultado

    corte = time.time() - max_edad_s
    try:
        with open(_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                ip = e.get("ip")
                if ip not in resultado:
                    continue
                # Filtrar por antigüedad
                try:
                    ts = datetime.fromisoformat(e["ts"]).timestamp()
                    if ts < corte:
                        continue
                except Exception:
                    pass
                resultado[ip].append(e)
    except Exception as e:
        print(f"[metrics] lectura: {e}")

    for ip in resultado:
        resultado[ip] = resultado[ip][-MAX_MUESTRAS:]
    return resultado


def historial_por_nodo(ips, last=MAX_MUESTRAS):
    """Compatibilidad con la firma antigua."""
    ips_set = set(ips or [])
    datos = _leer_recientes(ips_set)
    for ip in datos:
        datos[ip] = datos[ip][-last:]
    # Asegurar que todas las IPs están presentes aunque no tengan datos
    for ip in ips_set:
        datos.setdefault(ip, [])
    return datos


def stats_basicas(ip, last=60):
    muestras = historial_por_nodo([ip], last=last).get(ip, [])
    if not muestras:
        return {"n": 0}
    def _vals(campo):
        return [m[campo] for m in muestras if isinstance(m.get(campo), (int, float))]
    cpu, ram = _vals("cpu"), _vals("ram")
    return {
        "n":       len(muestras),
        "cpu_avg": round(sum(cpu) / len(cpu), 1) if cpu else None,
        "cpu_max": max(cpu) if cpu else None,
        "ram_avg": round(sum(ram) / len(ram), 1) if ram else None,
        "ram_max": max(ram) if ram else None,
        "primera": muestras[0]["ts"],
        "ultima":  muestras[-1]["ts"],
    }
