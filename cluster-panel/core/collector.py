import subprocess
import threading
import time
from datetime import datetime, timedelta

from .config import Config
from .extensions import db
from .models import ThermalReading, FanState, Setting, EventLog
from .utils import COMANDO_SAMPLE, parsear_linea_salida, log_event


class LiveState:
    def __init__(self):
        self.lock       = threading.Lock()
        self.nodes      = {}
        self.promedios  = {"temp": 0.0, "cpu": 0.0}
        self.temp_max   = 0.0
        self.cpu_max    = 0.0
        self.modo       = "auto"
        self.fans       = {}
        self.last_sample = None

    def snapshot(self):
        with self.lock:
            return {
                "nodes":       dict(self.nodes),
                "promedios":   dict(self.promedios),
                "temp_max":    self.temp_max,
                "cpu_max":     self.cpu_max,
                "modo":        self.modo,
                "fans":        dict(self.fans),
                "last_sample": self.last_sample.isoformat() if self.last_sample else None,
            }


live = LiveState()


def _procesar_salida_ansible(stdout):
    resultado = {}
    nodo_actual = None
    for linea in stdout.splitlines():
        if " | SUCCESS" in linea or " | CHANGED" in linea:
            nodo_actual = linea.split(" | ")[0].strip()
        elif " | UNREACHABLE" in linea or " | FAILED" in linea:
            ip = linea.split(" | ")[0].strip()
            resultado[ip] = {"online": False}
            nodo_actual = None
        elif nodo_actual and linea.strip():
            datos = parsear_linea_salida(linea.strip())
            if datos:
                datos["online"] = True
                resultado[nodo_actual] = datos
                nodo_actual = None
    return resultado


def _sample_once():
    try:
        cmd = [Config.ANSIBLE_BIN, "all", "-i", Config.ANSIBLE_INVENTORY,
               "-m", "shell", "-a", COMANDO_SAMPLE]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=Config.ANSIBLE_TIMEOUT,
                             cwd=Config.ANSIBLE_CWD)
        return _procesar_salida_ansible(res.stdout)
    except subprocess.TimeoutExpired:
        log_event("WARNING", "collector", "Ansible timeout")
        return {}
    except Exception as e:
        log_event("CRITICAL", "collector", f"Error: {e}")
        return {}


def _auto_ventiladores(temp_max):
    if temp_max < Config.FAN_MIN_TEMP:
        return 0
    if temp_max >= Config.FAN_MAX_TEMP:
        return 255
    ratio = (temp_max - Config.FAN_MIN_TEMP) / (Config.FAN_MAX_TEMP - Config.FAN_MIN_TEMP)
    return int((ratio ** 2) * 255)


def _aplicar_control_auto():
    from .arduino import arduino
    pwm = _auto_ventiladores(live.temp_max)
    for pin in ["11", "10", "6", "5"]:
        fs = db.session.get(FanState, pin)
        if fs:
            fs.value = pwm
            arduino.send(pin, pwm)
    db.session.commit()
    live.fans = {fs.pin: fs.value for fs in FanState.query.all()}


def _detectar_eventos(prev_online, curr):
    for ip, data in curr.items():
        estaba = prev_online.get(ip, True)
        ahora  = data.get("online", True)

        if estaba and not ahora:
            log_event("CRITICAL", "network", f"Nodo {ip} CAÍDO", node_ip=ip)
        elif not estaba and ahora:
            log_event("INFO", "network", f"Nodo {ip} recuperado", node_ip=ip)

        if ahora:
            temp = data.get("temp", 0)
            if temp >= Config.TEMP_CRITICAL:
                log_event("CRITICAL", "thermal",
                          f"Temp crítica en {ip}: {temp:.1f}°C", node_ip=ip)
            elif temp >= Config.TEMP_WARNING:
                log_event("WARNING", "thermal",
                          f"Temp alta en {ip}: {temp:.1f}°C", node_ip=ip)


def _cleanup_old():
    cutoff = datetime.utcnow() - timedelta(days=Config.RETENTION_DAYS)
    n1 = ThermalReading.query.filter(ThermalReading.timestamp < cutoff).delete()
    n2 = EventLog.query.filter(EventLog.timestamp < cutoff).delete()
    db.session.commit()
    if n1 or n2:
        log_event("INFO", "system",
                  f"Limpieza: {n1} lecturas, {n2} logs antiguos")


def collector_loop(app):
    print("[collector] Iniciado")
    prev_online = {}
    last_cleanup = time.time()

    while True:
        try:
            with app.app_context():
                data = _sample_once()
                if not data:
                    time.sleep(Config.SAMPLE_INTERVAL)
                    continue

                _detectar_eventos(prev_online, data)
                prev_online = {ip: d.get("online", True) for ip, d in data.items()}

                ahora = datetime.utcnow()
                for ip, d in data.items():
                    if not d.get("online"):
                        continue
                    db.session.add(ThermalReading(
                        node_ip=ip,
                        temp=d.get("temp"),
                        cpu=d.get("cpu"),
                        ram_used=d.get("ram_used"),
                        ram_total=d.get("ram_total"),
                        disk_pct=d.get("disk_pct"),
                        load1=d.get("load1"),
                        online=True,
                        timestamp=ahora,
                    ))
                db.session.commit()

                with live.lock:
                    live.nodes = data
                    live.last_sample = ahora
                    temps = [d["temp"] for d in data.values()
                             if d.get("online") and d.get("temp", 0) > 0]
                    cpus  = [d["cpu"] for d in data.values()
                             if d.get("online") and d.get("cpu", 0) > 0]
                    live.temp_max = max(temps) if temps else 0.0
                    live.cpu_max  = max(cpus) if cpus else 0.0
                    live.promedios["temp"] = sum(temps)/len(temps) if temps else 0.0
                    live.promedios["cpu"]  = sum(cpus)/len(cpus) if cpus else 0.0

                modo = Setting.get("modo", "auto")
                live.modo = modo
                if modo == "auto":
                    _aplicar_control_auto()

                if time.time() - last_cleanup > 86400:
                    _cleanup_old()
                    last_cleanup = time.time()

        except Exception as e:
            print(f"[collector] Error: {e}")
            log_event("CRITICAL", "collector", f"Error en loop: {e}")

        time.sleep(Config.SAMPLE_INTERVAL)
