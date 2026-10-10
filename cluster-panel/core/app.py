import json
import threading
import time
from datetime import datetime, timedelta

from flask import (Flask, render_template, jsonify, request,
                   Response, stream_with_context)

from .config import Config
from .extensions import db
from .models import Node, ThermalReading, EventLog, Setting, FanState
from .collector import live, collector_loop
from .arduino import arduino
from .utils import validar_ip, validar_mac, log_event


# Rutas absolutas al proyecto (templates/ y static/ en la raíz)
from pathlib import Path as _Path
_RAIZ = _Path(__file__).parent.parent


def create_app():
    app = Flask(
        __name__,
        template_folder=str(_RAIZ / "templates"),
        static_folder=str(_RAIZ / "static"),
    )
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_initial()

    # ── Arrancar hilos de fondo (idempotente) ────────────────
    # Con Gunicorn, main() no se ejecuta, así que hay que arrancar
    # los hilos aquí. Usamos un flag en app.config para no duplicar.
    if not app.config.get('_hilos_arrancados', False):
        app.config['_hilos_arrancados'] = True

        t_collector = threading.Thread(
            target=collector_loop, args=(app,),
            daemon=True, name='collector')
        t_collector.start()

        t_arduino = threading.Thread(
            target=arduino.reconnect_loop,
            daemon=True, name='arduino-reconnect')
        t_arduino.start()

        with app.app_context():
            log_event("INFO", "panel", "Panel iniciado (Gunicorn)")
        print("[app] Hilos de fondo arrancados")

    return app


def _seed_initial():
    if Node.query.count() == 0:
        ips = [f"10.4.8.{i}" for i in range(10, 19)]
        for ip in ips:
            n = Node(ip=ip, name=f"node-{ip.split('.')[-1]}",
                     group="manager" if ip.endswith(".10") else "workers",
                     role="manager" if ip.endswith(".10") else "worker")
            db.session.add(n)
        db.session.commit()
        print("[seed] Nodos iniciales creados")

    if FanState.query.count() == 0:
        for pin, nombre, tipo in [
            ("11", "Ventilador 1", "pwm"),
            ("10", "Ventilador 2", "pwm"),
            ("6",  "Ventilador 3", "pwm"),
            ("5",  "Ventilador 4", "pwm"),
            ("9",  "Relé Principal", "digital"),
        ]:
            db.session.add(FanState(pin=pin, name=nombre, tipo=tipo, value=0))
        db.session.commit()

    if Setting.get("modo") is None:
        Setting.set("modo", "auto")


app = create_app()


# ══════════════════════════════════════════════════════════
# VISTAS HTML
# ══════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html", active_tab="dashboard")


@app.route("/nodos")
def page_nodos():
    return render_template("nodes.html", active_tab="nodos")


@app.route("/logs")
def page_logs():
    return render_template("logs.html", active_tab="logs")


# ══════════════════════════════════════════════════════════
# API — Estado en vivo
# ══════════════════════════════════════════════════════════
@app.route("/api/estado")
def api_estado():
    return jsonify(live.snapshot())


@app.route("/api/stream")
def api_stream():
    @stream_with_context
    def gen():
        last_ts = None
        while True:
            snap = live.snapshot()
            ts = snap.get("last_sample")
            if ts != last_ts:
                last_ts = ts
                yield f"data: {json.dumps(snap)}\n\n"
            time.sleep(5)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# ══════════════════════════════════════════════════════════
# API — Nodos (CRUD)
# ══════════════════════════════════════════════════════════
@app.route("/api/nodes", methods=["GET"])
def api_nodes_list():
    return jsonify([n.to_dict() for n in Node.query.order_by(Node.ip).all()])


@app.route("/api/nodes", methods=["POST"])
def api_nodes_create():
    d = request.get_json() or {}
    ip = (d.get("ip") or "").strip()
    if not validar_ip(ip):
        return jsonify(error="IP inválida"), 400
    if d.get("mac") and not validar_mac(d["mac"]):
        return jsonify(error="MAC inválida"), 400
    if Node.query.filter_by(ip=ip).first():
        return jsonify(error="Ya existe un nodo con esa IP"), 409

    n = Node(
        ip=ip,
        name=(d.get("name") or f"node-{ip.split('.')[-1]}").strip(),
        mac=d.get("mac"),
        group=(d.get("group") or "workers").strip(),
        role=(d.get("role") or "worker").strip(),
        enabled=bool(d.get("enabled", True)),
        notes=d.get("notes"),
    )
    db.session.add(n)
    db.session.commit()
    log_event("INFO", "node", f"Nodo añadido: {ip}", node_ip=ip)
    return jsonify(n.to_dict()), 201


@app.route("/api/nodes/<int:nid>", methods=["PUT"])
def api_nodes_update(nid):
    n = db.session.get(Node, nid)
    if not n:
        return jsonify(error="No encontrado"), 404
    d = request.get_json() or {}
    if "ip" in d and not validar_ip(d["ip"]):
        return jsonify(error="IP inválida"), 400
    if d.get("mac") and not validar_mac(d["mac"]):
        return jsonify(error="MAC inválida"), 400

    for k in ("ip", "name", "mac", "group", "role", "notes"):
        if k in d:
            setattr(n, k, d[k])
    if "enabled" in d:
        n.enabled = bool(d["enabled"])
    db.session.commit()
    log_event("INFO", "node", f"Nodo actualizado: {n.ip}", node_ip=n.ip)
    return jsonify(n.to_dict())


@app.route("/api/nodes/<int:nid>", methods=["DELETE"])
def api_nodes_delete(nid):
    n = db.session.get(Node, nid)
    if not n:
        return jsonify(error="No encontrado"), 404
    ip = n.ip
    db.session.delete(n)
    db.session.commit()
    log_event("INFO", "node", f"Nodo eliminado: {ip}", node_ip=ip)
    return jsonify(ok=True)


@app.route("/api/nodes/<ip>/detail")
def api_node_detail(ip):
    if not validar_ip(ip):
        return jsonify(error="IP inválida"), 400

    import subprocess
    comando = r"""
echo "===UPTIME==="; uptime
echo "===FREE==="; free -m
echo "===DISK==="; df -h /
echo "===CPU_INFO==="; nproc; grep "model name" /proc/cpuinfo | head -1
echo "===TOP_CPU==="; ps aux --sort=-%cpu | head -11
echo "===TOP_MEM==="; ps aux --sort=-%mem | head -11
echo "===TEMP==="; for z in /sys/class/thermal/thermal_zone*/; do
    t=$(cat $z/type 2>/dev/null); v=$(cat $z/temp 2>/dev/null)
    echo "$t: $v"
done
"""
    try:
        cmd = [Config.ANSIBLE_BIN, ip, "-i", Config.ANSIBLE_INVENTORY,
               "-m", "shell", "-a", comando]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=Config.DETAIL_TIMEOUT,
                             cwd=Config.ANSIBLE_CWD)
        secciones = {}
        actual = None
        for linea in res.stdout.splitlines():
            if linea.startswith("===") and linea.endswith("==="):
                actual = linea.strip("=").strip()
                secciones[actual] = []
            elif actual and linea.strip() and " | " not in linea:
                secciones[actual].append(linea)
        return jsonify({"ip": ip, "sections": secciones, "raw": res.stdout})
    except subprocess.TimeoutExpired:
        return jsonify(error="Timeout consultando nodo"), 504
    except Exception as e:
        return jsonify(error=str(e)), 500


# ══════════════════════════════════════════════════════════
# API — Histórico
# ══════════════════════════════════════════════════════════
@app.route("/api/thermal/history")
def api_thermal_history():
    """Histórico agregado. Bucketing automático según rango:
         <= 2h  -> 1 min
         <= 12h -> 5 min
         <= 48h -> 15 min
         >  48h -> 60 min
    """
    horas = float(request.args.get("hours", 1))
    node_ip = request.args.get("node")
    cutoff = datetime.utcnow() - timedelta(hours=horas)

    # Elegir tamaño de bucket
    if horas <= 2:
        bucket_min = 1
    elif horas <= 12:
        bucket_min = 5
    elif horas <= 48:
        bucket_min = 15
    else:
        bucket_min = 60

    q = (ThermalReading.query
         .filter(ThermalReading.timestamp >= cutoff)
         .order_by(ThermalReading.timestamp.asc()))

    if node_ip:
        if not validar_ip(node_ip):
            return jsonify(error="IP inválida"), 400
        q = q.filter(ThermalReading.node_ip == node_ip)

    # Traer solo las columnas necesarias
    rows = q.with_entities(
        ThermalReading.node_ip,
        ThermalReading.timestamp,
        ThermalReading.temp,
        ThermalReading.cpu,
    ).all()

    # Agrupar por bucket
    buckets = {}
    for ip, ts, temp, cpu in rows:
        key_ts = ts.replace(
            minute=(ts.minute // bucket_min) * bucket_min,
            second=0, microsecond=0,
        )
        key = (ip, key_ts)
        if key not in buckets:
            buckets[key] = {"temps": [], "cpus": []}
        if temp is not None: buckets[key]["temps"].append(temp)
        if cpu  is not None: buckets[key]["cpus"].append(cpu)

    # Convertir a lista
    resultado = []
    for (ip, ts), vals in sorted(buckets.items(), key=lambda x: x[0][1]):
        resultado.append({
            "node_ip": ip,
            "timestamp": ts.isoformat() + "Z",
            "temp": round(sum(vals["temps"]) / len(vals["temps"]), 2) if vals["temps"] else None,
            "cpu":  round(sum(vals["cpus"])  / len(vals["cpus"]),  2) if vals["cpus"]  else None,
        })

    return jsonify(resultado)


# ══════════════════════════════════════════════════════════
# API — Estadísticas analíticas
# ══════════════════════════════════════════════════════════
@app.route("/api/stats")
def api_stats():
    node = request.args.get("node")
    hours = float(request.args.get("hours", 1))
    if not node or not validar_ip(node):
        return jsonify(error="Parámetro 'node' inválido"), 400

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = (ThermalReading.query
            .filter(ThermalReading.node_ip == node,
                    ThermalReading.timestamp >= cutoff)
            .order_by(ThermalReading.timestamp.asc())
            .all())

    if not rows:
        return jsonify({"node": node, "hours": hours, "count": 0, "metrics": {}})

    def stats_for(getter):
        vals = [v for v in (getter(r) for r in rows) if v is not None]
        if not vals:
            return {"min": 0, "max": 0, "avg": 0, "last": 0, "count": 0}
        return {
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "last": round(vals[-1], 2),
            "count": len(vals),
        }

    def ram_pct(r):
        if r.ram_total and r.ram_total > 0:
            return round(r.ram_used / r.ram_total * 100, 1)
        return None

    return jsonify({
        "node": node,
        "hours": hours,
        "count": len(rows),
        "first": rows[0].timestamp.isoformat(),
        "last":  rows[-1].timestamp.isoformat(),
        "metrics": {
            "temp":     stats_for(lambda r: r.temp),
            "cpu":      stats_for(lambda r: r.cpu),
            "ram_pct":  stats_for(ram_pct),
            "disk_pct": stats_for(lambda r: r.disk_pct),
            "load1":    stats_for(lambda r: r.load1),
        }
    })


@app.route("/api/thermal/series")
def api_thermal_series():
    nodes_param = request.args.get("nodes", "")
    hours  = float(request.args.get("hours", 1))
    metrics = [m.strip() for m in request.args.get("metrics", "temp,cpu").split(",") if m.strip()]
    bucket = int(request.args.get("bucket", 0))

    nodes = [n.strip() for n in nodes_param.split(",") if n.strip()]
    for n in nodes:
        if not validar_ip(n):
            return jsonify(error=f"IP inválida: {n}"), 400

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    q = ThermalReading.query.filter(ThermalReading.timestamp >= cutoff)
    if nodes:
        q = q.filter(ThermalReading.node_ip.in_(nodes))
    q = q.order_by(ThermalReading.timestamp.asc()).limit(20000)

    def extract(r, m):
        if m == "temp":  return r.temp
        if m == "cpu":   return r.cpu
        if m == "disk":  return r.disk_pct
        if m == "load":  return r.load1
        if m == "ram":
            if r.ram_total and r.ram_total > 0:
                return round(r.ram_used / r.ram_total * 100, 1)
        return None

    por_nodo = {}
    for r in q.all():
        por_nodo.setdefault(r.node_ip, []).append(r)

    def bucketizar(registros, minutos):
        if minutos <= 0:
            return registros
        salida = []
        cur_bucket = None
        acum = {m: [] for m in metrics}
        for r in registros:
            key = r.timestamp.replace(
                minute=(r.timestamp.minute // minutos) * minutos,
                second=0, microsecond=0)
            if key != cur_bucket:
                if cur_bucket is not None:
                    salida.append(_make_bucket(cur_bucket, acum, metrics))
                cur_bucket = key
                acum = {m: [] for m in metrics}
            for m in metrics:
                v = extract(r, m)
                if v is not None:
                    acum[m].append(v)
        if cur_bucket is not None:
            salida.append(_make_bucket(cur_bucket, acum, metrics))
        return salida

    def _make_bucket(ts, acum, metricas):
        item = {"t": ts.isoformat()}
        for m in metricas:
            vals = acum[m]
            item[m] = round(sum(vals) / len(vals), 2) if vals else None
        return item

    resultado = {}
    for ip, registros in por_nodo.items():
        if bucket > 0:
            resultado[ip] = bucketizar(registros, bucket)
        else:
            resultado[ip] = [{
                "t": r.timestamp.isoformat(),
                **{m: extract(r, m) for m in metrics}
            } for r in registros]

    return jsonify({
        "hours": hours,
        "metrics": metrics,
        "bucket_minutes": bucket,
        "series": resultado,
    })


# ══════════════════════════════════════════════════════════
# API — Logs
# ══════════════════════════════════════════════════════════
@app.route("/api/logs")
def api_logs():
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(500, int(request.args.get("limit", 50)))
    level = request.args.get("level")
    cat   = request.args.get("category")
    node  = request.args.get("node")

    q = EventLog.query
    if level: q = q.filter(EventLog.level == level)
    if cat:   q = q.filter(EventLog.category == cat)
    if node:  q = q.filter(EventLog.node_ip == node)

    total = q.count()
    items = (q.order_by(EventLog.timestamp.desc())
             .offset((page-1)*limit).limit(limit).all())

    return jsonify({
        "total": total, "page": page, "limit": limit,
        "items": [e.to_dict() for e in items],
    })


@app.route("/api/logs/summary")
def api_logs_summary():
    hours = float(request.args.get("hours", 24))
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    q = EventLog.query.filter(EventLog.timestamp >= cutoff)

    buckets = {}
    por_cat = {}
    por_level = {"INFO": 0, "WARNING": 0, "CRITICAL": 0}

    for e in q.all():
        key = e.timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
        if key not in buckets:
            buckets[key] = {"t": key, "INFO": 0, "WARNING": 0, "CRITICAL": 0, "total": 0}
        lvl = e.level or "INFO"
        if lvl not in buckets[key]:
            buckets[key][lvl] = 0
        buckets[key][lvl] += 1
        buckets[key]["total"] += 1

        por_level[lvl] = por_level.get(lvl, 0) + 1
        cat = e.category or "system"
        por_cat[cat] = por_cat.get(cat, 0) + 1

    serie = sorted(buckets.values(), key=lambda x: x["t"])

    return jsonify({
        "hours": hours,
        "total": sum(por_level.values()),
        "by_level": por_level,
        "by_category": por_cat,
        "by_hour": serie,
    })


# ══════════════════════════════════════════════════════════
# API — Fans
# ══════════════════════════════════════════════════════════
@app.route("/api/fans", methods=["GET"])
def api_fans():
    return jsonify([f.to_dict() for f in FanState.query.order_by(FanState.pin).all()])


@app.route("/api/fans/<pin>", methods=["POST"])
def api_fan_set(pin):
    fs = db.session.get(FanState, pin)
    if not fs:
        return jsonify(error="Pin no encontrado"), 404

    if Setting.get("modo", "auto") == "auto" and fs.tipo == "pwm":
        return jsonify(error="Bloqueado: modo automático activo"), 403

    d = request.get_json() or {}
    val = d.get("value")
    if not isinstance(val, int) or not (0 <= val <= 255):
        return jsonify(error="Valor debe ser entero 0-255"), 400

    fs.value = val
    db.session.commit()
    arduino.send(pin, val)
    # Actualizar estado en memoria inmediatamente
    with live.lock:
        live.fans[pin] = val
    log_event("INFO", "system", f"Fan {pin} → {val}", meta={"pin": pin, "value": val})
    return jsonify(fs.to_dict())


# ══════════════════════════════════════════════════════════
# API — Modo auto/manual
# ══════════════════════════════════════════════════════════
@app.route("/api/mode", methods=["GET"])
def api_mode_get():
    return jsonify({"modo": Setting.get("modo", "auto")})


@app.route("/api/mode", methods=["POST"])
def api_mode_set():
    d = request.get_json() or {}
    modo = d.get("modo")
    if modo not in ("auto", "manual"):
        return jsonify(error="Modo debe ser 'auto' o 'manual'"), 400
    Setting.set("modo", modo)
    # Actualizar estado en memoria inmediatamente para que el
    # dashboard lo refleje sin esperar al siguiente ciclo del collector
    with live.lock:
        live.modo = modo
    log_event("INFO", "system", f"Modo cambiado a {modo}")
    return jsonify({"modo": modo})


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
# API — Health check (Arduino + panel)
# ══════════════════════════════════════════════════════════
@app.route("/api/health")
def api_health():
    """Estado de salud del panel: Arduino, último muestreo."""
    return jsonify({
        "panel":         True,
        "arduino":       arduino.connected,
        "arduino_port":  Config.ARDUINO_PORT,
        "modo":          Setting.get("modo", "auto"),
        "last_sample":   live.last_sample.isoformat() if live.last_sample else None,
    })



def main():
    """Solo para desarrollo local con `python run.py`.
    En producción se usa gunicorn (ver interfaz-monitoreo.service)."""
    print(f"\n[🚀] Interfaz de Monitoreo (dev) en http://{Config.PANEL_HOST}:{Config.PANEL_PORT}\n")
    app.run(host=Config.PANEL_HOST, port=Config.PANEL_PORT,
            debug=False, threaded=True)


if __name__ == "__main__":
    main()
