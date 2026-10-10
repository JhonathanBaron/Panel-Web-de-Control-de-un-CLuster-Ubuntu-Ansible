from flask import (Flask, render_template, request, jsonify, session,
                   redirect, url_for, abort, send_file)
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import subprocess
import time
import threading
import re
import os
import shutil
import yaml

from config import Config
import credentials
from utils import (run_safe, run_ansible, run_playbook,
                   leer_usuarios, guardar_usuarios,
                   validar_ip, validar_username,
                   audit, leer_audit, run_remote_script)
from inventory import cargar_inventario, resumen_nodos, es_ip_valida
import tasks
import metrics
import nas
import cluster_users
import nodes
import inventory_editor
import apps_config
import ssh_client
import ssh_panel_keys
import user_admin



# ─── Caché de recursos (evita golpear los nodos cada request) ───
_REC_CACHE = {}          # {ip: (timestamp, data)}
_REC_CACHE_LOCK = threading.Lock()
_REC_CACHE_TTL  = 20     # segundos


# ─── Caché de nodos offline (evita martillar nodos caídos) ────
_OFFLINE_CACHE = {}          # {ip: timestamp_cuando_se_detecto_offline}
_OFFLINE_CACHE_TTL = 60      # segundos antes de reintentar


app = Flask(__name__)
app.config.from_object(Config)
app.config['MAX_CONTENT_LENGTH'] = Config.NAS_MAX_UPLOAD_MB * 1024 * 1024

csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app,
                  default_limits=["600 per hour"],
                  storage_uri="memory://")


# ══════════════════════════════════════════════════════════════
# AUTENTICACIÓN
# ══════════════════════════════════════════════════════════════
def requiere_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('usuario'):
            if request.is_json:
                return jsonify({"status": "error", "output": "Sesión expirada"}), 401
            return redirect(url_for('login'))
        # Refrescar rol desde credentials (panel + clúster vía PAM info)
        info = credentials.obtener_usuario(session.get('usuario')) or {}
        session['role']   = info.get('role', session.get('role', 'viewer'))
        session['nombre'] = info.get('nombre', session.get('usuario'))
        return f(*args, **kwargs)
    return decorated


# Jerarquía de roles del panel
ROLES_PANEL = ("viewer", "student", "operator", "admin")
ROLE_LEVELS = {"viewer": 1, "student": 2, "operator": 3, "admin": 4}


def requiere_rol(min_role):
    """Decorador: exige al menos un rol del panel."""
    def wrapper(f):
        @wraps(f)
        @requiere_login
        def decorated(*args, **kwargs):
            u = session.get('usuario')
            info_u = credentials.obtener_usuario(u) or {}
            actual = info_u.get("role", "viewer")
            if ROLE_LEVELS.get(actual, 0) < ROLE_LEVELS.get(min_role, 99):
                return jsonify({"status": "error",
                                "output": f"Requiere rol {min_role} o superior"}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper


def requiere_admin(f):
    """Atajo para requiere rol admin."""
    return requiere_rol("admin")(f)


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    error = None
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        password = request.form.get('password', '')
        info = credentials.verificar(usuario, password)
        if info:
            session.clear()
            session['usuario'] = usuario
            session['role']   = info.get('role', 'viewer')
            session['nombre'] = info.get('nombre', usuario)
            session.permanent = True
            audit(usuario, "login.ok", target=request.remote_addr,
                  detalle=f"origen={info.get('origen','?')}")
            return redirect(url_for('index'))
        audit(usuario or "anon", "login.fail", target=request.remote_addr,
              exito=False)
        error = 'Usuario o contraseña incorrectos.'
    return render_template('login.html', error=error, csrf_token=generate_csrf())


@app.route('/logout')
def logout():
    u = session.get('usuario', 'anon')
    audit(u, "logout")
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@requiere_login
def index():
    return render_template('index.html',
                           usuario=session.get('usuario'),
                           role=session.get('role', 'viewer'),
                           csrf_token=generate_csrf())


@app.route('/api/me')
@requiere_login
def api_me():
    u = session.get('usuario')
    info = credentials.obtener_usuario(u) or {}
    return jsonify({
        "usuario": u,
        "role":    info.get('role', session.get('role', 'viewer')),
        "nombre":  info.get('nombre', u),
        "origen":  info.get('origen', 'panel'),
    })


@app.route('/api/me/password', methods=['POST'])
@requiere_login
def api_me_password():
    """Cambiar tu propia contraseña.
    - Si eres cuenta del panel → hash local
    - Si eres usuario del clúster → chpasswd vía ansible
    """
    d = request.json or {}
    actual = d.get("actual", "")
    nueva = d.get("nueva", "")
    usuario = session.get('usuario')

    if len(nueva) < 8:
        return jsonify({"status": "error",
                        "output": "La nueva contraseña debe tener mínimo 8 caracteres"}), 400

    info = credentials.verificar(usuario, actual)
    if not info:
        audit(usuario, "password.change", exito=False)
        return jsonify({"status": "error", "output": "Contraseña actual incorrecta"}), 401

    origen = info.get("origen", "panel")
    if origen == "panel":
        credentials.cambiar_password(usuario, nueva)
    else:
        # Usuario del clúster: cambiar la contraseña en todos los nodos
        try:
            cmd = ["ansible", "cluster", "-i", Config.INVENTORY, "-b", "-m", "shell",
                   "-a", f"echo '{usuario}:{nueva}' | chpasswd"]
            rc, out, err = run_safe(cmd, timeout=60, cwd=Config.ANSIBLE_DIR)
            if rc != 0:
                audit(usuario, "password.change", exito=False)
                return jsonify({"status": "error",
                                "output": (out + err).strip()[-500:]}), 500
        except Exception as e:
            return jsonify({"status": "error", "output": str(e)}), 500

    audit(usuario, "password.change", detalle=f"origen={origen}")
    return jsonify({"status": "success", "output": "Contraseña actualizada"})



@app.route('/api/inventory')
@requiere_login
def api_inventory():
    try:
        inv = cargar_inventario()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    return jsonify({
        "status": "success",
        "grupos": {
            k: {"hosts": v["hosts"], "children": v["children"]}
            for k, v in inv["grupos"].items()
        },
        "hosts": resumen_nodos(),
    })


@app.route('/api/nodos/estado')
@requiere_login
def api_nodos_estado():
    """Ping a todos los nodos EN PARALELO. No bloquea si hay nodos offline."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    nodos = resumen_nodos()

    def _ping(n):
        rc, _, _ = run_safe(
            ["ping", "-c", "1", "-W", "1", n["ip"]], timeout=2)
        return n["ip"], rc == 0

    resultado = {}
    with ThreadPoolExecutor(max_workers=min(16, len(nodos) or 1)) as ex:
        futuros = {ex.submit(_ping, n): n for n in nodos}
        for fut in as_completed(futuros, timeout=6):
            n = futuros[fut]
            try:
                ip, online = fut.result()
            except Exception:
                ip, online = n["ip"], False
            resultado[ip] = {
                "nombre": n["nombre"],
                "rol":    n["rol"],
                "grupos": n["grupos"],
                "online": online,
            }

    # Cualquier nodo que no haya respondido → offline
    for n in nodos:
        if n["ip"] not in resultado:
            resultado[n["ip"]] = {
                "nombre": n["nombre"],
                "rol":    n["rol"],
                "grupos": n["grupos"],
                "online": False,
            }

    return jsonify({"status": "success", "nodos": resultado})




# ─── Resolver el usuario SSH correcto por nodo ─────────────────
_SSH_USER_CACHE = {}

def _usuario_ssh_de_nodo(ip):
    """Devuelve el ansible_user del inventario para esa IP.
    Fallback a 'cluster0' si no se encuentra."""
    if ip in _SSH_USER_CACHE:
        return _SSH_USER_CACHE[ip]
    user = 'cluster0'
    try:
        for n in resumen_nodos():
            if n.get('ip') == ip:
                u = (n.get('usuario') or '').strip()
                if u:
                    user = u
                break
    except Exception:
        pass
    _SSH_USER_CACHE[ip] = user
    return user


@app.route('/api/nodos/<ip>/recursos')
@requiere_login
def api_nodos_recursos(ip):
    """Recursos del nodo vía SSH directo + caché 20s."""
    if not validar_ip(ip) or not es_ip_valida(ip):
        return jsonify({"status": "error", "output": "Nodo desconocido"}), 404

    # ─── 1) ¿Está en caché? ─────────────────────────────────
    ahora = time.time()
    with _REC_CACHE_LOCK:
        cached = _REC_CACHE.get(ip)
        if cached and (ahora - cached[0]) < _REC_CACHE_TTL:
            return jsonify({
                "status": "success",
                "nodo": ip,
                "cached": True,
                "recursos": cached[1],
            })

    # ─── 2) Script (una sola línea de comandos vía SSH) ─────
    script = (
        "export LC_ALL=C LANG=C; "
        "echo 'MEM:'$(free -m | awk '/^Mem:/ {print $2, $3, $7}'); "
        "echo 'DISK:'$(df -h / | awk 'NR==2 {print $2, $3, $4, $5}'); "
        "echo 'CPU:'$(top -bn1 | grep 'Cpu(s)' | head -1); "
        "echo 'LOAD:'$(cat /proc/loadavg); "
        "echo 'CORES:'$(nproc)"
    )

        # ─── 3) ¿Está marcado como offline hace poco? ──────────
    offline_ts = _OFFLINE_CACHE.get(ip, 0)
    if ahora - offline_ts < _OFFLINE_CACHE_TTL:
        return jsonify({
            "status": "error",
            "output": "Nodo offline (reintento en unos segundos)",
            "offline": True,
        }), 503

    # ─── 4) Ejecutar SSH con usuario correcto (1 solo intento) ─
    usuario_ssh = _usuario_ssh_de_nodo(ip)
    rc, out, err = ssh_client.run_ssh(
        ip, script, user=usuario_ssh, timeout=3)

    # ─── 5) Si falla por credenciales → probar con cluster0 ─
    # Solo si el error es "Permission denied", no si es timeout
    err_str = (err or '') + (out or '')
    if rc != 0 and 'Permission denied' in err_str and usuario_ssh != 'cluster0':
        rc0, out0, err0 = ssh_client.run_ssh(
            ip, script, user='cluster0', timeout=3)
        if rc0 == 0 and 'MEM:' in out0:
            rc, out, err = rc0, out0, err0

    # ─── 6) Si sigue fallando → marcar offline y devolver error ──
    if rc != 0 or 'MEM:' not in out:
        # ¿Es un error de red/timeout? → marcar offline
        if any(kw in err_str for kw in (
                'timed out', 'Connection refused', 'No route',
                'banner exchange', 'Connection closed',
                'No such host', 'Network is unreachable')):
            import time as _time
            _OFFLINE_CACHE[ip] = _time.time()

        # Fallback único a Ansible con timeout corto (solo si no es offline)
        if ip not in _OFFLINE_CACHE or (
                _time.time() - _OFFLINE_CACHE.get(ip, 0)) < 1:
            try:
                rc2, out2, err2 = run_remote_script(ip, script, timeout=8)
                if rc2 == 0 and 'MEM:' in out2:
                    rc, out, err = rc2, out2, err2
                    _OFFLINE_CACHE.pop(ip, None)
                else:
                    msg = (err or out or 'sin respuesta')[:120].strip()
                    return jsonify({
                        "status": "error",
                        "output": f"Nodo no responde: {msg}",
                        "offline": True,
                    }), 503
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "output": f"Nodo no responde: {e}",
                    "offline": True,
                }), 503
        else:
            return jsonify({
                "status": "error",
                "output": "Nodo offline",
                "offline": True,
            }), 503

    # ─── 7) Si llegó respuesta, limpiar caché de offline ──────
    _OFFLINE_CACHE.pop(ip, None)


    # ─── 8) Parsear por prefijos ────────────────────────────
    datos = {}
    for linea in out.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        for prefijo in ('MEM:', 'DISK:', 'CPU:', 'LOAD:', 'CORES:'):
            idx = linea.find(prefijo)
            if idx >= 0:
                datos[prefijo[:-1].lower()] = linea[idx + len(prefijo):].strip()
                break

    faltan = [k for k in ('mem', 'disk', 'cpu', 'load', 'cores') if k not in datos]
    if faltan:
        return jsonify({
            "status": "error",
            "output": f"salida incompleta ({', '.join(faltan)})",
            "raw": out[:500],
        }), 500

    try:
        mem_parts  = datos['mem'].split()
        disk_parts = datos['disk'].split()
        cpu_line   = datos['cpu']
        load_parts = datos['load'].split()
        cores      = datos['cores']

        m_idle = re.search(r'(\d+[.,]\d+)\s*id', cpu_line)
        idle   = float(m_idle.group(1).replace(',', '.')) if m_idle else 0.0
        cpu_used = round(max(0.0, min(100.0, 100 - idle)), 1)

        total_mb = int(mem_parts[0])
        usado_mb = int(mem_parts[1])
        libre_mb = int(mem_parts[2]) if len(mem_parts) > 2 else (total_mb - usado_mb)
        ram_pct  = round(usado_mb / total_mb * 100, 1) if total_mb else 0.0

        disk_pct = int(disk_parts[3].rstrip('%')) if len(disk_parts) > 3 else 0

        load3 = []
        for x in load_parts[:3]:
            try: load3.append(float(x))
            except ValueError: load3.append(0.0)
        while len(load3) < 3:
            load3.append(0.0)

        recursos = {
            "cpu": {
                "cores": int(cores) if cores.isdigit() else 0,
                "usado_pct": cpu_used,
                "load": load3,
            },
            "ram": {
                "total_mb": total_mb, "usado_mb": usado_mb,
                "libre_mb": libre_mb, "usado_pct": ram_pct,
            },
            "disco": {
                "total": disk_parts[0], "usado": disk_parts[1],
                "libre": disk_parts[2] if len(disk_parts) > 2 else "",
                "usado_pct": disk_pct,
            },
        }

        # ─── 5) Guardar en caché ────────────────────────────
        with _REC_CACHE_LOCK:
            _REC_CACHE[ip] = (ahora, recursos)

        # ─── 6) Guardar histórico (con rate-limit interno) ──
        try:
            metrics.recordar(
                ip, cpu_pct=cpu_used, ram_pct=ram_pct,
                disk_pct=disk_pct, load=load3,
            )
        except Exception:
            pass

        return jsonify({
            "status": "success",
            "nodo": ip,
            "cached": False,
            "recursos": recursos,
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "output": f"Parse: {e}",
            "raw": out[:500],
        }), 500


@app.route('/api/nodos/<ip>/herramientas')
@requiere_login
def api_nodos_herramientas(ip):
    if not validar_ip(ip) or not es_ip_valida(ip):
        return jsonify({"status": "error", "output": "Nodo desconocido"}), 404

    # Leer la lista editable desde data/herramientas.json
    try:
        conf = apps_config.leer_herramientas()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    categorias = conf.get("categorias", [])
    todas = []
    for cat in categorias:
        for t in cat.get("herramientas", []):
            if t not in todas:
                todas.append(t)

    if not todas:
        return jsonify({"status": "success", "nodos": {}})

    lineas_script = []
    for t in todas:
        # Validación defensiva: rechazar caracteres raros
        if not re.fullmatch(r"[a-zA-Z0-9_.+-]+", t):
            continue
        lineas_script.append(
            f"command -v {t} >/dev/null 2>&1 && echo '{t}:OK' || echo '{t}:FALTA'"
        )
    script = "\n".join(lineas_script)

    rc, out, err = run_remote_script(ip, script, timeout=30)
    if rc != 0:
        return jsonify({"status": "error",
                        "output": (err or out).strip()}), 500

    estado = {}
    for linea in out.splitlines():
        if ":" not in linea or "|" in linea[:40]:
            continue
        partes = linea.split(":", 1)
        if len(partes) != 2:
            continue
        t = partes[0].strip()
        st = partes[1].strip()
        if t in todas:
            estado[t] = (st == "OK")

    resultado = {}
    for cat in categorias:
        nombre = cat.get("nombre", "?")
        resultado[nombre] = {
            t: estado.get(t, False) for t in cat.get("herramientas", [])
        }

    return jsonify({"status": "success", "nodos": resultado})


# ══════════════════════════════════════════════════════════════
# APLICACIONES — gestionadas desde data/apps.json
# ══════════════════════════════════════════════════════════════
def _check_url(host, puerto, proto, path):
    url = f"{proto}://{host}:{puerto}{path}"
    rc, out, _ = run_safe(
        ["curl", "-ks", "-o", "/dev/null", "-w", "%{http_code}",
         "--max-time", "4", url],
        timeout=6)
    return out.strip() == "200"


def _check_cmd(host, comando):
    try:
        rc, _, _ = ssh_client.run_ssh(host, comando, timeout=6)
        return rc == 0
    except Exception:
        return False


def _estado_app(app):
    chk   = app.get("check") or {}
    tipo  = chk.get("tipo", "url")
    valor = chk.get("valor", "/")
    try:
        if tipo == "url":
            return "activo" if _check_url(
                app["host"], int(app["puerto"]),
                app.get("proto", "http"), valor) else "inactivo"
        if tipo == "cmd":
            return "activo" if _check_cmd(app["host"], valor) else "inactivo"
    except Exception as e:
        print(f"[apps] {app.get('id')}: {e}")
    return "inactivo"


@app.route('/api/apps', methods=['GET'])
@requiere_login
def api_apps_get():
    try:
        data = apps_config.leer_apps()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    out = []
    for app in data.get("apps", []):
        item = dict(app)
        item["estado"] = _estado_app(app)
        item["url"] = (f'{app.get("proto","http")}://'
                       f'{app["host"]}:{app["puerto"]}')
        out.append(item)
    return jsonify({"status": "success", "apps": out})


@app.route('/api/apps', methods=['PUT'])
@requiere_admin
def api_apps_put():
    body = request.json or {}
    try:
        data = apps_config.guardar_apps(body)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "apps.update",
          detalle=f"{len(data['apps'])} apps")
    return jsonify({"status": "success", "output": "Apps guardadas"})


@app.route('/api/apps/<app_id>/<action>', methods=['POST'])
@requiere_rol("operator")
def api_apps_control(app_id, action):
    if action not in ("start", "stop", "uninstall"):
        return jsonify({"status": "error", "output": "Acción inválida"}), 400

    data = apps_config.leer_apps()
    app = next((a for a in data.get("apps", []) if a.get("id") == app_id), None)
    if not app:
        return jsonify({"status": "error", "output": "App no encontrada"}), 404

    cfg = app.get(action) or {}
    if not cfg or not cfg.get("valor"):
        return jsonify({"status": "error",
                        "output": f"La app '{app_id}' no define '{action}'"}), 400

    tipo   = cfg.get("tipo")
    valor  = cfg.get("valor")
    usuario = session.get('usuario')

    try:
        if tipo == "playbook":
            rc, out, err = run_playbook(valor, timeout=900)
        elif tipo == "systemd":
            state = {"start": "started",
                     "stop":  "stopped",
                     "uninstall": "stopped"}[action]
            cmd = ["ansible", app["host"], "-i", Config.INVENTORY, "-b",
                   "-m", "systemd", "-a", f"name={valor} state={state}"]
            rc, out, err = run_safe(cmd, timeout=60, cwd=Config.ANSIBLE_DIR)
        else:
            return jsonify({"status": "error", "output": "tipo no soportado"}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(usuario, f"app.{app_id}.{action}", target=valor, exito=(rc == 0))
    return jsonify({
        "status": "success" if rc == 0 else "error",
        "output": (out + err).strip()[-3000:],
    })


@app.route('/api/apps/<app_id>', methods=['DELETE'])
@requiere_admin
def api_apps_delete(app_id):
    body = request.json or {}
    hacer_uninstall = bool(body.get("uninstall", False))

    data = apps_config.leer_apps()
    app = next((a for a in data.get("apps", []) if a.get("id") == app_id), None)
    if not app:
        return jsonify({"status": "error", "output": "App no encontrada"}), 404

    if hacer_uninstall:
        cfg = app.get("uninstall") or {}
        if not cfg.get("valor"):
            return jsonify({"status": "error",
                            "output": f"La app '{app_id}' no tiene playbook de "
                                      "desinstalación definido"}), 400
        try:
            rc, out, err = run_playbook(cfg["valor"], timeout=900)
        except Exception as e:
            return jsonify({"status": "error", "output": str(e)}), 500
        if rc != 0:
            audit(session.get('usuario'), f"app.{app_id}.uninstall",
                  target=cfg["valor"], exito=False)
            return jsonify({"status": "error",
                            "output": (out + err).strip()[-2500:]}), 500

    data["apps"] = [a for a in data["apps"] if a.get("id") != app_id]
    apps_config.guardar_apps(data)

    audit(session.get('usuario'), f"app.{app_id}.delete",
          detalle=f"uninstall={hacer_uninstall}")
    return jsonify({
        "status": "success",
        "output": (f"App '{app_id}' quitada del panel" +
                   (" y desinstalada del clúster" if hacer_uninstall else "")),
    })


# ══════════════════════════════════════════════════════════════
# HERRAMIENTAS — gestionadas desde data/herramientas.json
# ══════════════════════════════════════════════════════════════
@app.route('/api/herramientas', methods=['GET'])
@requiere_login
def api_herramientas_get():
    try:
        data = apps_config.leer_herramientas()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    return jsonify({"status": "success", **data})


@app.route('/api/herramientas', methods=['PUT'])
@requiere_admin
def api_herramientas_put():
    body = request.json or {}
    try:
        data = apps_config.guardar_herramientas(body)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "herramientas.update",
          detalle=f"{len(data['categorias'])} categorías")
    return jsonify({"status": "success", "output": "Herramientas guardadas"})


# ══════════════════════════════════════════════════════════════
# USUARIOS
# ══════════════════════════════════════════════════════════════
@app.route('/api/usuarios', methods=['GET'])
@requiere_login
def api_usuarios_listar():
    data = leer_usuarios()
    return jsonify({
        "status": "success",
        "usuarios": data.get("users", []),
        "config": data.get("config", {})
    })


@app.route('/api/usuarios', methods=['POST'])
@requiere_admin
def api_usuarios_crear():
    d = request.json or {}
    username = (d.get("username") or "").strip().lower()
    fullname = (d.get("fullname") or "").strip()
    role     = (d.get("role") or "student").strip()
    uid      = d.get("uid")
    expires  = d.get("expires")
    password = d.get("password") or ""

    if not validar_username(username):
        return jsonify({"status": "error",
                        "output": "Username inválido (a-z, 0-9, ., -, _)"}), 400
    if not fullname:
        return jsonify({"status": "error", "output": "Nombre completo requerido"}), 400
    if role not in ("professor", "student", "guest"):
        return jsonify({"status": "error", "output": "Rol inválido"}), 400
    if len(password) < 8:
        return jsonify({"status": "error",
                        "output": "La contraseña es obligatoria (mín. 8 caracteres)"}), 400

    data = leer_usuarios()
    usuarios = data.get("users", [])
    if any(u.get("username") == username for u in usuarios):
        return jsonify({"status": "error", "output": f"{username} ya existe"}), 409

    if not uid:
        rango = {"professor": (20000, 29999),
                 "student":   (30000, 39999),
                 "guest":     (40000, 49999)}[role]
        usados = [u.get("uid", 0) for u in usuarios
                  if rango[0] <= u.get("uid", 0) <= rango[1]]
        uid = max(usados) + 1 if usados else rango[0] + 1

    nuevo = {
        "username": username, "fullname": fullname, "uid": uid,
        "role": role, "active": True,
        "created": datetime.now().strftime("%Y-%m-%d")
    }
    if expires:
        nuevo["expires"] = str(expires)

    usuarios.append(nuevo)
    data["users"] = usuarios
    guardar_usuarios(data)

    rc, out, err = run_playbook("20_users.yml", timeout=180)
    out_full = (out + err).strip()

    # 1) Guardar hash local en credentials.enc (para login del panel)
    hash_ok = False
    try:
        rol_panel = credentials._rol_panel_desde_cluster(role)
        credentials.crear_usuario(
            usuario=username,
            password=password,
            role=rol_panel,
            nombre=fullname,
            origen="cluster",
        )
        hash_ok = True
        print(f"[user.create] {username}: hash local guardado (rol_panel={rol_panel})")
    except Exception as e:
        print(f"[user.create] {username}: ERROR guardando hash: {e}")

    # 2) Aplicar chpasswd en todos los nodos
    pwd_rc, pwd_out, pwd_err = run_safe(
        ["ansible", "cluster", "-i", Config.INVENTORY, "-b", "-m", "shell",
         "-a", f"echo '{username}:{password}' | chpasswd"],
        timeout=90, cwd=Config.ANSIBLE_DIR
    )
    pwd_ok = (pwd_rc == 0)

    # Distribuir la clave SSH maestra del panel al nuevo usuario
    clave_msg = ""
    try:
        resultado_clave, _, _ = ssh_panel_keys.distribuir_a_usuario(username)
        n_ok = sum(1 for v in resultado_clave.values() if v == 'OK')
        n_nf = sum(1 for v in resultado_clave.values() if v == 'NOT_FOUND')
        if n_ok > 0:
            clave_msg = f"clave SSH en {n_ok} nodos"
            if n_nf:
                clave_msg += f" ({n_nf} sin el usuario)"
        else:
            clave_msg = "clave SSH no distribuida"
    except Exception as e:
        clave_msg = f"clave SSH: {e}"
        print(f"[user.create] distribuir clave: {e}")

    # Añadirlo al detalle de la auditoría
    _detalle_create = (
        f"uid={uid} role={role} playbook_ok={rc == 0} "
        f"pass_ok={pwd_ok} hash_ok={hash_ok} | {clave_msg}"
    )

    audit(session.get('usuario'), "user.create", target=username,
          detalle=f"uid={uid} role={role} playbook_ok={rc == 0} pass_ok={pwd_ok} hash_ok={hash_ok}",
          exito=(rc == 0 and pwd_ok and hash_ok))

    partes = [f"Usuario {username} (UID {uid}) creado."]
    partes.append(f"Playbook: {'OK' if rc == 0 else 'FALLÓ'}")
    partes.append(f"Hash panel: {'OK' if hash_ok else 'FALLÓ'}")
    partes.append(f"Contraseña Linux: {'aplicada' if pwd_ok else 'FALLÓ'}")
    partes.append("")
    partes.append(out_full[-1500:])

    return jsonify({
        "status": "success" if (rc == 0 and pwd_ok and hash_ok) else "error",
        "output": chr(10).join(partes),
        "usuario": nuevo,
        "hash_ok": hash_ok,
        "pwd_ok": pwd_ok,
    })


@app.route('/api/usuarios/<username>', methods=['DELETE'])
@requiere_admin
def api_usuarios_eliminar(username):
    """Elimina el usuario de TODAS las fuentes posibles:
    - users.yaml
    - /etc/passwd en todos los nodos del clúster
    - home en el NAS
    - credentials.enc
    Funciona aunque solo esté en alguna de ellas.
    """
    if not cluster_users.validar_username(username):
        return jsonify({"status": "error", "output": "Username inválido"}), 400

    resultados = []
    encontrado = False

    # ─────────────────────────────────────────────────────
    # 1) Quitar del YAML (si está)
    # ─────────────────────────────────────────────────────
    try:
        data = leer_usuarios()
        antes = len(data.get("users", []))
        data["users"] = [u for u in data.get("users", [])
                         if u.get("username") != username]
        if len(data["users"]) < antes:
            guardar_usuarios(data)
            resultados.append("✓ Eliminado del YAML")
            encontrado = True
        else:
            resultados.append("· No estaba en el YAML")
    except Exception as e:
        resultados.append(f"⚠ Error YAML: {e}")

    # ─────────────────────────────────────────────────────
    # 2) userdel en todos los nodos del clúster
    # ─────────────────────────────────────────────────────
    userdel_ok = True
    try:
        # userdel SIN -r (el home está en el NAS, lo borramos aparte)
        # Al final verificamos con `id` si el usuario realmente sigue existiendo
        script = (
            f"pkill -u {username} 2>/dev/null; sleep 1; "
            f"userdel -f {username} >/dev/null 2>&1; "
            f"if id {username} >/dev/null 2>&1; then "
            f"  echo BORRADO=no; "
            f"else "
            f"  echo BORRADO=si; "
            f"fi"
        )
        cmd = ["ansible", "cluster", "-i", Config.INVENTORY, "-b",
               "-m", "shell", "-a", script]
        rc1, o, e = run_safe(cmd, timeout=120, cwd=Config.ANSIBLE_DIR)

        # Contar cuántos nodos dicen BORRADO=si
        salida = o or ""
        n_si = salida.count("BORRADO=si")
        n_no = salida.count("BORRADO=no")

        if n_no == 0 and n_si > 0:
            resultados.append(f"✓ Eliminado del clúster ({n_si} nodos confirmados)")
            encontrado = True
        elif n_si > 0:
            resultados.append(f"⚠ Eliminado en {n_si} nodos, falló en {n_no}")
            userdel_ok = False
            encontrado = True
        else:
            resultados.append("⚠ No se pudo verificar el borrado en el clúster")
            userdel_ok = False
    except Exception as e:
        userdel_ok = False
        resultados.append(f"⚠ userdel falló: {e}")

    # ─────────────────────────────────────────────────────
    # 3) Home en el NAS
    # ─────────────────────────────────────────────────────
    try:
        cmd2 = ["ansible", "nas", "-i", Config.INVENTORY, "-b",
                "-m", "shell", "-a",
                f"rm -rf {Config.NAS_BASE}/{username} 2>/dev/null; echo done"]
        rc2, o2, _ = run_safe(cmd2, timeout=60, cwd=Config.ANSIBLE_DIR)
        if rc2 == 0:
            resultados.append("✓ Home borrado del NAS")
        else:
            resultados.append("⚠ No se pudo borrar home del NAS")
    except Exception as e:
        resultados.append(f"⚠ NAS: {e}")

    # ─────────────────────────────────────────────────────
    # 4) credentials.enc
    # ─────────────────────────────────────────────────────
    try:
        if credentials.tiene_hash(username):
            credentials.eliminar_usuario(username)
            resultados.append("✓ Cuenta del panel eliminada")
            encontrado = True
    except Exception:
        pass

    # ─────────────────────────────────────────────────────
    # Resultado
    # ─────────────────────────────────────────────────────
    if not encontrado:
        return jsonify({
            "status": "error",
            "output": f"{username} no se encontró en ninguna fuente",
        }), 404

    audit(session.get('usuario'), "user.delete", target=username,
          exito=userdel_ok,
          detalle=" | ".join(r for r in resultados if r.startswith("✓")))

    return jsonify({
        "status": "success" if userdel_ok else "error",
        "output": f"{username} eliminado" + chr(10) + chr(10) + chr(10).join(resultados),
    })


@app.route('/api/usuarios/<username>/password', methods=['POST'])
@requiere_admin
def api_usuarios_password(username):
    """Cambia la contraseña de un usuario del clúster.
    - Guarda el hash en credentials.enc (creándolo si no existe)
    - Aplica chpasswd en todos los nodos del clúster
    """
    nueva = (request.json or {}).get("password", "").strip()
    if len(nueva) < 8:
        return jsonify({"status": "error",
                        "output": "Mínimo 8 caracteres"}), 400

    # 1) Recuperar info del usuario para conocer su rol
    info_cluster = None
    try:
        import cluster_users
        for x in cluster_users.listar_combinado().get("users", []):
            if x.get("username") == username:
                info_cluster = x
                break
    except Exception:
        pass

    if not info_cluster:
        # Buscar en users.yaml directo
        try:
            data = leer_usuarios()
            for u in data.get("users", []):
                if u.get("username") == username:
                    info_cluster = u
                    break
        except Exception:
            pass

    if not info_cluster:
        return jsonify({"status": "error",
                        "output": f"{username} no existe"}), 404

    rol_cluster = info_cluster.get("role", "student")
    rol_panel   = credentials._rol_panel_desde_cluster(rol_cluster)
    nombre      = info_cluster.get("fullname") or username

    # 2) Guardar/actualizar SIEMPRE el hash local
    try:
        existe = credentials.tiene_hash(username)
        if existe:
            credentials.cambiar_password(username, nueva)
            accion = "actualizado"
        else:
            credentials.crear_usuario(
                usuario=username,
                password=nueva,
                role=rol_panel,
                nombre=nombre,
                origen="cluster",
            )
            accion = "creado"
        print(f"[password] {username}: hash local {accion} (rol_panel={rol_panel})")
    except Exception as e:
        return jsonify({"status": "error",
                        "output": f"Error guardando credencial local: {e}"}), 500

    # 3) Aplicar chpasswd en todos los nodos (best effort)
    chpasswd_msg = ""
    try:
        cmd = ["ansible", "cluster", "-i", Config.INVENTORY, "-b",
               "-m", "shell",
               "-a", f"echo '{username}:{nueva}' | chpasswd"]
        rc, out, err = run_safe(cmd, timeout=90, cwd=Config.ANSIBLE_DIR)
        if rc == 0:
            chpasswd_msg = " · aplicado en el sistema"
        else:
            chpasswd_msg = " · ⚠ no aplicado al sistema (solo al panel)"
    except Exception as e:
        chpasswd_msg = f" · ⚠ chpasswd error: {e}"

    audit(session.get('usuario'), "user.password", target=username,
          detalle=f"rol_panel={rol_panel}{chpasswd_msg}")

    return jsonify({
        "status": "success",
        "output": f"Contraseña de {username} actualizada en el panel{chpasswd_msg}",
        "rol_panel": rol_panel,
    })


@app.route('/api/audit')
@requiere_login
def api_audit():
    limite = min(int(request.args.get("limit", 200)), 1000)
    usuario = request.args.get("usuario") or None
    accion = request.args.get("accion") or None
    return jsonify({
        "status": "success",
        "entries": leer_audit(limite=limite, filtro_usuario=usuario, filtro_accion=accion)
    })


# ══════════════════════════════════════════════════════════════
# COMANDOS Y PLAYBOOKS (legacy mantenido)
# ══════════════════════════════════════════════════════════════
@app.route('/api/ejecutar', methods=['POST'])
@requiere_login
def api_ejecutar():
    d = request.json or {}
    accion = d.get('accion')
    objetivo = d.get('objetivo', 'all')
    extra = (d.get('extra') or '').strip()
    usuario = session.get('usuario')

    if accion == 'ping':
        rc, out, err = run_ansible(objetivo, "ping", timeout=30)
        return jsonify({"status": "success" if rc == 0 else "error",
                        "output": (out + err).strip()})

    if accion == 'comando_libre':
        if not extra:
            return jsonify({"status": "error", "output": "Falta comando"}), 400
        rc, out, err = run_remote_script(objetivo, extra, timeout=60)
        audit(usuario, "cmd.adhoc", target=objetivo, detalle=extra)
        return jsonify({"status": "success" if rc == 0 else "error",
                        "output": (out + err).strip()})

    if accion == 'wakeonlan':
        rc, out, err = run_safe(["bash", Config.MAC_SCRIPT], timeout=30)
        audit(usuario, "power.wol", exito=(rc == 0))
        return jsonify({"status": "success" if rc == 0 else "error",
                        "output": (out + err).strip()})

    if accion in ('reboot', 'poweroff'):
        module = "reboot" if accion == "reboot" else "command"
        args = "" if accion == "reboot" else "poweroff"
        rc, out, err = run_ansible(objetivo, module, args, become=True, timeout=60)
        audit(usuario, f"power.{accion}", target=objetivo)
        return jsonify({"status": "success" if rc == 0 else "error",
                        "output": (out + err).strip()})

    return jsonify({"status": "error", "output": f"Acción no soportada: {accion}"}), 400


PLAYBOOKS_BACKUP_DIR = os.path.join(Config.DATA_DIR, "playbooks-backup")
PLAYBOOK_MAX_BYTES = 200 * 1024      # 200 KB por playbook
PLAYBOOK_BACKUPS_MAX = 20            # máx. backups por playbook


def _validar_nombre_pb(nombre):
    """Devuelve (ok, motivo). Nombre seguro: [A-Za-z0-9._-]+.yml/.yaml, sin paths."""
    if not nombre or len(nombre) > 80:
        return False, "Nombre inválido"
    if any(c in nombre for c in ("/", chr(92))) or ".." in nombre or nombre.startswith("."):
        return False, "Nombre contiene caracteres no permitidos"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(ya?ml)", nombre):
        return False, "Debe terminar en .yml o .yaml"
    return True, ""


def _path_playbook(nombre):
    return os.path.join(Config.PLAYBOOKS, nombre)


def _backup_playbook(nombre):
    """Guarda una copia del playbook actual antes de sobrescribir."""
    path = _path_playbook(nombre)
    if not os.path.isfile(path):
        return None
    dst_dir = os.path.join(PLAYBOOKS_BACKUP_DIR, nombre)
    os.makedirs(dst_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(dst_dir, f"{ts}.yml")
    shutil.copy2(path, dst)
    # Limitar a los N backups más recientes
    backups = sorted(os.listdir(dst_dir))
    if len(backups) > PLAYBOOK_BACKUPS_MAX:
        for viejo in backups[:-PLAYBOOK_BACKUPS_MAX]:
            try: os.unlink(os.path.join(dst_dir, viejo))
            except Exception: pass
    return os.path.basename(dst)


PLAYBOOKS_BACKUP_DIR = os.path.join(Config.DATA_DIR, "playbooks-backup")
PLAYBOOK_MAX_BYTES = 200 * 1024      # 200 KB por playbook
PLAYBOOK_BACKUPS_MAX = 20            # máx. backups por playbook


def _validar_nombre_pb(nombre):
    """Devuelve (ok, motivo). Nombre seguro: [A-Za-z0-9._-]+.yml/.yaml, sin paths."""
    if not nombre or len(nombre) > 80:
        return False, "Nombre inválido"
    if any(c in nombre for c in ("/", chr(92))) or ".." in nombre or nombre.startswith("."):
        return False, "Nombre contiene caracteres no permitidos"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(ya?ml)", nombre):
        return False, "Debe terminar en .yml o .yaml"
    return True, ""


def _path_playbook(nombre):
    return os.path.join(Config.PLAYBOOKS, nombre)


def _backup_playbook(nombre):
    """Guarda una copia del playbook actual antes de sobrescribir."""
    path = _path_playbook(nombre)
    if not os.path.isfile(path):
        return None
    dst_dir = os.path.join(PLAYBOOKS_BACKUP_DIR, nombre)
    os.makedirs(dst_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(dst_dir, f"{ts}.yml")
    shutil.copy2(path, dst)
    # Limitar a los N backups más recientes
    backups = sorted(os.listdir(dst_dir))
    if len(backups) > PLAYBOOK_BACKUPS_MAX:
        for viejo in backups[:-PLAYBOOK_BACKUPS_MAX]:
            try: os.unlink(os.path.join(dst_dir, viejo))
            except Exception: pass
    return os.path.basename(dst)


@app.route('/api/playbooks')
@requiere_login
def api_playbooks():
    import glob as _g
    archivos = sorted(_g.glob(f"{Config.PLAYBOOKS}/*.yml") +
                      _g.glob(f"{Config.PLAYBOOKS}/*.yaml"))
    items = []
    for a in archivos:
        try:
            st = os.stat(a)
            items.append({
                "nombre": os.path.basename(a),
                "size":   st.st_size,
                "mtime":  datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
        except Exception:
            items.append({"nombre": os.path.basename(a), "size": 0, "mtime": ""})
    return jsonify({"status": "success", "playbooks": items})


@app.route('/api/playbooks/leer')
@requiere_login
def api_playbooks_leer():
    nombre = request.args.get("nombre", "")
    ok, motivo = _validar_nombre_pb(nombre)
    if not ok:
        return jsonify({"status": "error", "output": motivo}), 400
    path = _path_playbook(nombre)
    if not os.path.isfile(path):
        return jsonify({"status": "error", "output": "No encontrado"}), 404
    try:
        with open(path) as f:
            contenido = f.read()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    st = os.stat(path)
    return jsonify({
        "status": "success",
        "nombre": nombre,
        "contenido": contenido,
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    })


@app.route('/api/playbooks/crear', methods=['POST'])
@requiere_rol("operator")
def api_playbooks_crear():
    d = request.json or {}
    nombre = (d.get("nombre") or "").strip()
    contenido = d.get("contenido") or ""

    ok, motivo = _validar_nombre_pb(nombre)
    if not ok:
        return jsonify({"status": "error", "output": motivo}), 400
    if len(contenido.encode()) > PLAYBOOK_MAX_BYTES:
        return jsonify({"status": "error", "output": "Contenido demasiado grande (>200KB)"}), 400

    path = _path_playbook(nombre)
    if os.path.exists(path):
        return jsonify({"status": "error", "output": f"Ya existe {nombre}"}), 409

    # Validar YAML
    try:
        if contenido.strip():
            yaml.safe_load(contenido)
    except yaml.YAMLError as e:
        return jsonify({"status": "error", "output": f"YAML inválido: {e}"}), 400

    try:
        with open(path, "w") as f:
            f.write(contenido)
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(session.get('usuario'), "playbook.create", target=nombre)
    return jsonify({"status": "success", "output": f"Playbook {nombre} creado", "nombre": nombre})


@app.route('/api/playbooks/guardar', methods=['POST'])
@requiere_rol("operator")
def api_playbooks_guardar():
    d = request.json or {}
    nombre = (d.get("nombre") or "").strip()
    contenido = d.get("contenido") or ""

    ok, motivo = _validar_nombre_pb(nombre)
    if not ok:
        return jsonify({"status": "error", "output": motivo}), 400
    path = _path_playbook(nombre)
    if not os.path.isfile(path):
        return jsonify({"status": "error", "output": "Playbook no encontrado"}), 404
    if len(contenido.encode()) > PLAYBOOK_MAX_BYTES:
        return jsonify({"status": "error", "output": "Contenido demasiado grande"}), 400

    # Validar YAML
    try:
        yaml.safe_load(contenido)
    except yaml.YAMLError as e:
        return jsonify({"status": "error", "output": f"YAML inválido: {e}"}), 400

    backup = _backup_playbook(nombre)
    try:
        with open(path, "w") as f:
            f.write(contenido)
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(session.get('usuario'), "playbook.save", target=nombre,
          detalle=f"backup={backup or 'sin backup'}")
    return jsonify({"status": "success", "output": f"Guardado ({backup or 'sin backup'})",
                    "backup": backup})


@app.route('/api/playbooks/<nombre>', methods=['DELETE'])
@requiere_rol("operator")
def api_playbooks_eliminar(nombre):
    ok, motivo = _validar_nombre_pb(nombre)
    if not ok:
        return jsonify({"status": "error", "output": motivo}), 400
    path = _path_playbook(nombre)
    if not os.path.isfile(path):
        return jsonify({"status": "error", "output": "No encontrado"}), 404

    # Backup antes de eliminar (por si se arrepiente)
    _backup_playbook(nombre)
    try:
        os.unlink(path)
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(session.get('usuario'), "playbook.delete", target=nombre)
    return jsonify({"status": "success", "output": f"{nombre} eliminado"})


@app.route('/api/playbooks/<nombre>/backups')
@requiere_login
def api_playbooks_backups(nombre):
    ok, motivo = _validar_nombre_pb(nombre)
    if not ok:
        return jsonify({"status": "error", "output": motivo}), 400
    dst_dir = os.path.join(PLAYBOOKS_BACKUP_DIR, nombre)
    if not os.path.isdir(dst_dir):
        return jsonify({"status": "success", "backups": []})
    items = []
    for f in sorted(os.listdir(dst_dir), reverse=True):
        try:
            st = os.stat(os.path.join(dst_dir, f))
            items.append({
                "nombre": f,
                "size":   st.st_size,
                "mtime":  datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
        except Exception:
            pass
    return jsonify({"status": "success", "backups": items})


@app.route('/api/playbooks/<nombre>/restore', methods=['POST'])
@requiere_rol("operator")
def api_playbooks_restore(nombre):
    ok, motivo = _validar_nombre_pb(nombre)
    if not ok:
        return jsonify({"status": "error", "output": motivo}), 400
    backup_name = (request.json or {}).get("backup", "")
    if "/" in backup_name or ".." in backup_name:
        return jsonify({"status": "error", "output": "Backup inválido"}), 400

    src_backup = os.path.join(PLAYBOOKS_BACKUP_DIR, nombre, backup_name)
    if not os.path.isfile(src_backup):
        return jsonify({"status": "error", "output": "Backup no encontrado"}), 404

    # Guardar el actual como backup antes de restaurar
    _backup_playbook(nombre)
    try:
        shutil.copy2(src_backup, _path_playbook(nombre))
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(session.get('usuario'), "playbook.restore", target=nombre, detalle=backup_name)
    return jsonify({"status": "success", "output": f"Restaurado desde {backup_name}"})




@app.route('/api/playbooks/ejecutar', methods=['POST'])
@requiere_rol('operator')
def api_playbooks_ejecutar():
    """Lanza el playbook en background. Devuelve task_id inmediatamente."""
    nombre = (request.json or {}).get("nombre", "")
    if not nombre or "/" in nombre or ".." in nombre:
        return jsonify({"status": "error", "output": "Nombre inválido"}), 400
    path = os.path.join(Config.PLAYBOOKS, nombre)
    if not os.path.isfile(path):
        return jsonify({"status": "error", "output": "Playbook no encontrado"}), 404

    cmd = ["ansible-playbook", "-i", Config.INVENTORY, path]
    t = tasks.lanzar(
        kind="playbook",
        cmd=cmd,
        cwd=Config.ANSIBLE_DIR,
        timeout=1800,
        meta={"usuario": session.get('usuario'), "nombre": nombre},
    )
    audit(session.get('usuario'), "playbook.run", target=nombre)
    return jsonify({"status": "success", "task_id": t.id})



# ══════════════════════════════════════════════════════════════
# TAREAS EN BACKGROUND (playbooks, comandos largos)
# ══════════════════════════════════════════════════════════════
@app.route('/api/tasks')
@requiere_login
def api_tasks_listar():
    try:
        limit = min(int(request.args.get("limit", 30)), 100)
    except Exception:
        limit = 30
    solo_mios = request.args.get("mios") == "1"
    usuario = session.get('usuario') if solo_mios else None
    return jsonify({
        "status": "success",
        "tasks": [t.to_dict(with_output=False)
                  for t in tasks.listar(limit=limit, solo_usuario=usuario)]
    })


@app.route('/api/tasks/<task_id>')
@requiere_login
def api_tasks_ver(task_id):
    t = tasks.obtener(task_id)
    if not t:
        return jsonify({"status": "error", "output": "Tarea no encontrada"}), 404
    try:
        since = int(request.args.get("since", 0))
    except Exception:
        since = 0
    return jsonify({"status": "success",
                    "task": t.to_dict(with_output=True, since=since)})


@app.route('/api/tasks/<task_id>/cancelar', methods=['POST'])
@requiere_rol("operator")
def api_tasks_cancelar(task_id):
    t = tasks.obtener(task_id)
    if not t:
        return jsonify({"status": "error", "output": "Tarea no encontrada"}), 404
    if t.status != "running":
        return jsonify({"status": "error", "output": "La tarea ya terminó"}), 400
    t.timeout = 0
    return jsonify({"status": "success", "output": "Cancelación solicitada"})


# ══════════════════════════════════════════════════════════════
# MÉTRICAS HISTÓRICAS (sparklines)
# ══════════════════════════════════════════════════════════════
@app.route('/api/metrics/sparklines')
@requiere_login
def api_metrics_sparklines():
    """Devuelve el histórico reciente de CPU/RAM/Disco por nodo."""
    try:
        last = min(int(request.args.get("last", 60)), 300)
    except Exception:
        last = 60

    ips_param = request.args.get("ips")
    if ips_param:
        ips = [x.strip() for x in ips_param.split(",") if x.strip()]
    else:
        try:
            ips = [n["ip"] for n in resumen_nodos()]
        except Exception:
            ips = []

    datos = metrics.historial_por_nodo(ips, last=last)
    return jsonify({"status": "success", "sparklines": datos})


@app.route('/api/metrics/stats/<ip>')
@requiere_login
def api_metrics_stats(ip):
    """Resumen estadístico de un nodo."""
    if not validar_ip(ip) or not es_ip_valida(ip):
        return jsonify({"status": "error", "output": "Nodo desconocido"}), 404
    try:
        last = min(int(request.args.get("last", 60)), 300)
    except Exception:
        last = 60
    return jsonify({"status": "success", "stats": metrics.stats_basicas(ip, last=last)})



# ══════════════════════════════════════════════════════════════
# NAS — navegador de archivos
# ══════════════════════════════════════════════════════════════
def _usuario_nas():
    """Devuelve el usuario cuyo NAS se está consultando.
    - Usuarios normales: siempre su propio usuario
    - admin/operator: pueden pasar ?user=<nombre> para ver el NAS de otro
    """
    propio = session.get('usuario')
    solicitado = (request.args.get('user') or '').strip()

    if not solicitado or solicitado == propio:
        return propio

    # Solo admin puede ver NAS ajenos. Operator (profesores) NO.
    info = credentials.obtener_usuario(propio) or {}
    rol = info.get('role', session.get('role', 'viewer'))
    if rol != 'admin':
        # Registrar el intento si lo hizo maliciosamente
        try:
            from utils import audit
            audit(propio, "nas.acceso_denegado",
                  target=solicitado,
                  detalle=f"rol={rol} intentó ver NAS ajeno",
                  exito=False)
        except Exception:
            pass
        return propio

    # Validar el nombre del usuario solicitado
    if not re.fullmatch(r'[a-z][a-z0-9._-]{0,31}', solicitado.lower()):
        return propio

    return solicitado.lower()


@app.route('/api/nas/list')
@requiere_login
def api_nas_list():
    usuario = _usuario_nas()
    if not usuario:
        return jsonify({"status": "error", "output": "Sin sesión"}), 401
    try:
        nas.asegurar_home(usuario)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    try:
        data = nas.listar(usuario, request.args.get("path", ""))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    return jsonify({"status": "success", **data,
                    "uso_bytes": nas.uso_disco(usuario)})


@app.route('/api/nas/info')
@requiere_login
def api_nas_info():
    usuario = _usuario_nas()
    try:
        data = nas.info(usuario, request.args.get("path", ""))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    return jsonify({"status": "success", **data})


@app.route('/api/nas/download')
@requiere_login
def api_nas_download():
    usuario = _usuario_nas()
    try:
        p = nas.resolver(usuario, request.args.get("path", ""), debe_existir=True)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    if p.is_dir():
        return jsonify({"status": "error", "output": "Es un directorio"}), 400
    audit(usuario, "nas.download", target=request.args.get("path", ""))
    return send_file(str(p), as_attachment=True, download_name=p.name)


@app.route('/api/nas/upload', methods=['POST'])
@requiere_login
def api_nas_upload():
    usuario = _usuario_nas()
    if "file" not in request.files:
        return jsonify({"status": "error", "output": "Sin archivo"}), 400
    f = request.files["file"]
    rel = request.form.get("path", "")
    try:
        info = nas.guardar_upload(usuario, rel, f)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(usuario, "nas.upload", target=info["rel"], detalle=f"{info['size']} bytes")
    return jsonify({"status": "success", **info})


@app.route('/api/nas/mkdir', methods=['POST'])
@requiere_login
def api_nas_mkdir():
    usuario = _usuario_nas()
    d = request.json or {}
    try:
        rel = nas.mkdir(usuario, d.get("path", ""), d.get("nombre", ""))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    audit(usuario, "nas.mkdir", target=rel)
    return jsonify({"status": "success", "rel": rel})


@app.route('/api/nas/rename', methods=['POST'])
@requiere_login
def api_nas_rename():
    usuario = _usuario_nas()
    d = request.json or {}
    try:
        rel = nas.renombrar(usuario, d.get("path", ""), d.get("nuevo", ""))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    audit(usuario, "nas.rename", target=d.get("path", ""), detalle=rel)
    return jsonify({"status": "success", "rel": rel})


@app.route('/api/nas/delete', methods=['POST'])
@requiere_login
def api_nas_delete():
    usuario = _usuario_nas()
    d = request.json or {}
    path = d.get("path", "")
    try:
        nas.eliminar(usuario, path)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    audit(usuario, "nas.delete", target=path)
    return jsonify({"status": "success"})


@app.route('/api/nas/wget', methods=['POST'])
@requiere_login
def api_nas_wget():
    usuario = _usuario_nas()
    d = request.json or {}
    url = d.get("url", "")
    rel = d.get("path", "")
    try:
        url = nas.validar_url_wget(url)
        destino = nas.resolver(usuario, rel, debe_existir=True)
        if not destino.is_dir():
            return jsonify({"status": "error", "output": "El destino no es un directorio"}), 400
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400

    cmd = ["wget", "-c", "--progress=dot:giga",
           "-P", str(destino), url]
    t = tasks.lanzar(
        kind="wget",
        cmd=cmd,
        cwd=str(destino),
        timeout=7200,
        meta={"usuario": usuario, "url": url, "path": rel, "nombre": f"wget {url}"},
    )
    audit(usuario, "nas.wget", target=rel, detalle=url)
    return jsonify({"status": "success", "task_id": t.id})



@app.route('/api/nas/download-zip')
@requiere_login
def api_nas_download_zip():
    """Empaqueta la carpeta (o el home) y la descarga como ZIP."""
    usuario = _usuario_nas()
    rel = request.args.get("path", "")
    try:
        zip_path, nombre = nas.crear_zip_de(usuario, rel)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(usuario, "nas.download_zip", target=rel or "(home)", detalle=nombre)

    # Programar borrado tras enviar
    @after_this_request
    def _cleanup(response):
        try: os.unlink(zip_path)
        except Exception: pass
        return response

    return send_file(
        zip_path,
        as_attachment=True,
        download_name=nombre,
        mimetype="application/zip",
    )



@app.route('/api/nas/diagnostico')
@requiere_rol("operator")
def api_nas_diagnostico():
    """Diagnóstico del NAS: rutas, permisos, usuario, home."""
    import os as _os
    from pathlib import Path as _Path
    info = {
        "usuario_sesion": session.get('usuario'),
        "usuario_linux":  _os.getenv("USER"),
        "nas_base":       str(Config.NAS_BASE),
        "nas_base_existe": _Path(Config.NAS_BASE).exists(),
        "nas_base_w":     _os.access(Config.NAS_BASE, _os.W_OK)
                          if _Path(Config.NAS_BASE).exists() else None,
    }
    try:
        home = nas.home_de(session.get('usuario'))
        info["home_path"]  = str(home)
        info["home_existe"] = home.exists()
        if home.exists():
            info["home_w"] = _os.access(str(home), _os.W_OK)
            try:
                info["home_contenido"] = len(list(home.iterdir()))
            except Exception:
                pass
    except Exception as e:
        info["home_error"] = str(e)
    return jsonify({"status": "success", "info": info})






@app.route('/api/nas/usuarios')
@requiere_rol("operator")
def api_nas_usuarios():
    """Lista los usuarios con carpeta en el NAS.
    Solo devuelve carpetas cuyo nombre es un username válido."""
    from pathlib import Path as _Path
    try:
        base = _Path(Config.NAS_BASE)
        if not base.exists():
            return jsonify({"status": "success", "usuarios": []})

        usuarios = []
        for d in sorted(base.iterdir()):
            if not d.is_dir() or d.name.startswith('.'):
                continue
            # Solo carpetas con nombre tipo username
            if not re.fullmatch(r'[a-z][a-z0-9._-]{0,31}', d.name):
                continue
            size = 0
            try:
                size = nas.uso_disco(d.name)
            except Exception:
                pass
            usuarios.append({"username": d.name, "size": size})

        return jsonify({"status": "success", "usuarios": usuarios})
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "output": str(e),
            "tb": traceback.format_exc()[-500:],
        }), 500


# ══════════════════════════════════════════════════════════════
# NAS — preview + bulk
# ══════════════════════════════════════════════════════════════
@app.route('/api/nas/preview')
@requiere_login
def api_nas_preview():
    usuario = _usuario_nas()
    try:
        data = nas.preview(usuario, request.args.get("path", ""))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    return jsonify({"status": "success", "preview": data})


@app.route('/api/nas/raw')
@requiere_login
def api_nas_raw():
    """Sirve el contenido crudo de un archivo (para imágenes, PDF)."""
    usuario = _usuario_nas()
    try:
        p = nas.resolver(usuario, request.args.get("path", ""), debe_existir=True)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    if p.is_dir():
        return jsonify({"status": "error", "output": "Es un directorio"}), 400
    mt = nas.mimetype_de(p.name)
    return send_file(str(p), mimetype=mt, as_attachment=False)


@app.route('/api/nas/delete-multiple', methods=['POST'])
@requiere_login
def api_nas_delete_multiple():
    usuario = _usuario_nas()
    rels = (request.json or {}).get("paths") or []
    if not isinstance(rels, list) or not rels:
        return jsonify({"status": "error", "output": "Sin rutas"}), 400
    if len(rels) > 500:
        return jsonify({"status": "error", "output": "Máximo 500 items"}), 400
    try:
        res = nas.eliminar_muchos(usuario, rels)
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(usuario, "nas.delete_multiple",
          target=f"{len(res['eliminados'])} items",
          detalle=",".join(res["eliminados"])[:500])
    return jsonify({"status": "success", **res})


@app.route('/api/nas/move', methods=['POST'])
@requiere_login
def api_nas_move():
    usuario = _usuario_nas()
    d = request.json or {}
    rels = d.get("paths") or []
    destino = d.get("destino", "")
    if not isinstance(rels, list) or not rels:
        return jsonify({"status": "error", "output": "Sin rutas"}), 400
    try:
        res = nas.mover(usuario, rels, destino)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(usuario, "nas.move", target=f"{len(res['movidos'])} items",
          detalle=f"→ {destino}")
    return jsonify({"status": "success", **res})


@app.route('/api/nas/download-zip-multi')
@requiere_login
def api_nas_download_zip_multi():
    usuario = _usuario_nas()
    raw = request.args.get("paths", "")
    rels = [x for x in raw.split(",") if x.strip()]
    if not rels:
        return jsonify({"status": "error", "output": "Sin rutas"}), 400
    try:
        zip_path, nombre = nas.crear_zip_multiple(usuario, rels)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    audit(usuario, "nas.download_zip_multi", target=f"{len(rels)} items",
          detalle=nombre)

    @after_this_request
    def _cleanup(response):
        try: os.unlink(zip_path)
        except Exception: pass
        return response

    return send_file(zip_path, as_attachment=True,
                     download_name=nombre, mimetype="application/zip")



# ══════════════════════════════════════════════════════════════
# USUARIOS v2 — combinado YAML + sistema
# ══════════════════════════════════════════════════════════════
@app.route('/api/usuarios/v2')
@requiere_login
def api_usuarios_v2():
    try:
        combo = cluster_users.listar_combinado()
        res   = cluster_users.resumen()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    return jsonify({"status": "success", **combo, "resumen": res})


@app.route('/api/usuarios/sistema')
@requiere_login
def api_usuarios_sistema():
    try:
        return jsonify({"status": "success",
                        "usuarios": cluster_users.usuarios_sistema()})
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500


@app.route('/api/usuarios/sync-import', methods=['POST'])
@requiere_admin
def api_usuarios_sync_import():
    try:
        añadidos = cluster_users.importar_del_sistema()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "users.sync_import",
          target=f"{len(añadidos)} importados",
          detalle=",".join(añadidos[:20]))
    return jsonify({
        "status": "success",
        "output": f"{len(añadidos)} usuario(s) importado(s) del sistema",
        "añadidos": añadidos,
    })


@app.route('/api/usuarios/<username>', methods=['PUT'])
@requiere_admin
def api_usuarios_editar(username):
    """Edita el usuario y aplica automáticamente al sistema."""
    if not cluster_users.validar_username(username):
        return jsonify({"status": "error", "output": "Username inválido"}), 400
    d = request.json or {}
    try:
        u = cluster_users.editar(username, d)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    # Aplicar al sistema automáticamente
    try:
        rc, out, err = run_playbook("20_users.yml", timeout=180)
        aplicado_ok = (rc == 0)
    except Exception as e:
        aplicado_ok = False
        out, err = "", str(e)

    audit(session.get('usuario'), "user.edit", target=username,
          detalle=f"campos={','.join(d.keys())} aplicado={aplicado_ok}",
          exito=aplicado_ok)

    msg = f"{username} actualizado"
    if aplicado_ok:
        msg += " y aplicado al sistema"
    else:
        msg += " — ⚠ falló al aplicar al sistema (mira el log)"

    return jsonify({
        "status": "success" if aplicado_ok else "error",
        "output": msg + chr(10) + chr(10) + (out + err).strip()[-800:],
        "usuario": u,
        "aplicado": aplicado_ok,
    })


@app.route('/api/usuarios/aplicar', methods=['POST'])
@requiere_admin
def api_usuarios_aplicar():
    """Aplica el users.yaml al sistema vía playbook 20_users.yml."""
    try:
        rc, out, err = run_playbook("20_users.yml", timeout=300)
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "users.apply",
          exito=(rc == 0),
          detalle=f"rc={rc}")
    return jsonify({
        "status": "success" if rc == 0 else "error",
        "output": (out + err).strip()[-4000:],
        "rc": rc,
    })



@app.route('/api/usuarios/_diagnostico')
@requiere_admin
def api_usuarios_diagnostico():
    """Diagnóstico interno: qué usuarios están en cada fuente."""
    try:
        creds = credentials._load_creds()
        creds_info = [
            {"username": u, "role": info.get("role"),
             "origen": info.get("origen", "panel")}
            for u, info in creds.items()
        ]
    except Exception as e:
        creds_info = [{"error": str(e)}]

    try:
        import cluster_users
        yaml_info = cluster_users.listar_combinado().get("users", [])
    except Exception as e:
        yaml_info = [{"error": str(e)}]

    return jsonify({
        "status": "success",
        "pam_disponible": credentials.PAM_DISPONIBLE,
        "credentials": creds_info,
        "cluster":     yaml_info,
    })



@app.route('/api/usuarios/auto-sync', methods=['POST'])
@requiere_admin
def api_usuarios_auto_sync():
    """Sincroniza automáticamente: importa del sistema si hace falta."""
    try:
        añadidos = cluster_users.importar_del_sistema()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    return jsonify({
        "status": "success",
        "añadidos": añadidos,
        "n": len(añadidos),
    })



# ══════════════════════════════════════════════════════════════
# CONFIG DE NODOS (MAC, WOL) + POWER POR NODO
# ══════════════════════════════════════════════════════════════
@app.route('/api/nodos/config')
@requiere_login
def api_nodos_config_listar():
    try:
        conf = nodes.todos()
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    salida = {}
    for n in resumen_nodos():
        ip = n["ip"]
        c = conf.get(ip, {})
        salida[ip] = {
            "nombre": c.get("nombre") or n["nombre"],
            "rol":    n["rol"],
            "grupos": n["grupos"],
            "mac":    c.get("mac", ""),
            "wol":    c.get("wol", False),
        }
    return jsonify({"status": "success", "nodos": salida})


@app.route('/api/nodos/<ip>/config', methods=['PUT'])
@requiere_rol("operator")
def api_nodos_config_actualizar(ip):
    if not validar_ip(ip) or not es_ip_valida(ip):
        return jsonify({"status": "error", "output": "Nodo desconocido"}), 404
    d = request.json or {}
    cambios = {}
    if "nombre" in d:
        cambios["nombre"] = str(d["nombre"]).strip()[:64]
    if "mac" in d:
        mac = nodes.validar_mac(d["mac"] or "")
        if d["mac"] and not mac:
            return jsonify({"status": "error",
                            "output": "MAC inválida (usa aa:bb:cc:dd:ee:ff)"}), 400
        cambios["mac"] = mac or ""
    if "wol" in d:
        cambios["wol"] = bool(d["wol"])
    if not cambios:
        return jsonify({"status": "error", "output": "Nada que actualizar"}), 400

    try:
        cfg = nodes.actualizar(ip, cambios)
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "node.config", target=ip,
          detalle=",".join(cambios.keys()))
    return jsonify({"status": "success", "config": cfg})


@app.route('/api/nodos/<ip>/power/<accion>', methods=['POST'])
@requiere_rol("operator")
def api_nodos_power(ip, accion):
    if not validar_ip(ip) or not es_ip_valida(ip):
        return jsonify({"status": "error", "output": "Nodo desconocido"}), 404
    if accion not in ("on", "off", "reboot"):
        return jsonify({"status": "error", "output": "Acción inválida"}), 400

    usuario = session.get('usuario')
    nombre = nodes.obtener(ip).get("nombre") or ip

    if accion == "on":
        try:
            mac = nodes.enviar_wol(ip)
        except ValueError as e:
            return jsonify({"status": "error", "output": str(e)}), 400
        except Exception as e:
            return jsonify({"status": "error", "output": "WOL falló: " + str(e)}), 500
        audit(usuario, "power.on", target=ip, detalle="mac=" + mac)
        return jsonify({"status": "success",
                        "output": "Magic packet enviado a " + nombre + " (" + ip + ") — MAC " + mac})

    if accion == "reboot":
        rc, out, err = run_ansible(ip, "reboot", "", become=True, timeout=60)
        audit(usuario, "power.reboot", target=ip, exito=(rc == 0))
        return jsonify({
            "status": "success" if rc == 0 else "error",
            "output": (out + err).strip()[-1500:],
        })

    if accion == "off":
        rc, out, err = run_ansible(ip, "command", "poweroff", become=True, timeout=60)
        audit(usuario, "power.off", target=ip, exito=(rc == 0))
        return jsonify({
            "status": "success" if rc == 0 else "error",
            "output": (out + err).strip()[-1500:],
        })



@app.route('/api/nodos/detectar-macs', methods=['POST'])
@requiere_rol("operator")
def api_nodos_detectar_macs():
    """Ejecuta ansible setup a TODOS los nodos y guarda las MACs."""
    import json as _json
    import subprocess as _sub
    import re as _re

    env = os.environ.copy()
    env["ANSIBLE_DISPLAY_SKIPPED_HOSTS"] = "False"
    env["ANSIBLE_DISPLAY_OK_HOSTS"] = "True"
    env.pop("ANSIBLE_STDOUT_CALLBACK", None)
    env.pop("ANSIBLE_CALLBACKS_ENABLED", None)

    cmd = [
        "ansible", "all", "-i", Config.INVENTORY,
        "-m", "setup", "-a", "filter=ansible_default_ipv4",
        "-o",
    ]

    try:
        res = _sub.run(cmd, capture_output=True, text=True,
                       timeout=180, cwd=Config.ANSIBLE_DIR, env=env)
    except _sub.TimeoutExpired:
        return jsonify({"status": "error",
                        "output": "Timeout de ansible (>180s)"}), 500
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500

    salida = res.stdout or ""
    if not salida.strip():
        return jsonify({
            "status": "error",
            "output": "Sin salida de ansible",
            "raw": (res.stderr or "")[-1500:],
        }), 500

    detectadas = {}
    errores = []
    hosts_consultados = 0

    patron = _re.compile(r'^([0-9.]+)\s*\|\s*(SUCCESS|CHANGED|UNREACHABLE|FAILED)\s*=>\s*(\{.*\})\s*$')

    for linea in salida.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if "|" in linea and "=>" in linea:
            hosts_consultados += 1
        m = patron.match(linea)
        if not m:
            continue
        ip, estado, json_str = m.group(1), m.group(2), m.group(3)
        if estado in ("UNREACHABLE", "FAILED"):
            try:
                info = _json.loads(json_str)
                msg = (info.get("msg") or "")[:150]
            except Exception:
                msg = json_str[:150]
            errores.append({"ip": ip, "error": msg})
            continue
        try:
            info = _json.loads(json_str)
        except Exception as e:
            errores.append({"ip": ip, "error": "JSON: " + str(e)})
            continue
        facts = (info.get("ansible_facts") or {}).get("ansible_default_ipv4") or {}
        mac = (facts.get("macaddress") or "").strip().lower()
        if mac:
            detectadas[ip] = mac
        else:
            errores.append({"ip": ip, "error": "sin macaddress"})

    actualizadas = []
    for ip, mac in detectadas.items():
        try:
            nodes.actualizar(ip, {"mac": mac})
            actualizadas.append({"ip": ip, "mac": mac})
        except Exception as e:
            errores.append({"ip": ip, "error": "guardar: " + str(e)})

    audit(session.get('usuario'), "node.detect_macs",
          target=str(len(actualizadas)) + " nodos",
          detalle=",".join(a["ip"] for a in actualizadas[:15]))

    return jsonify({
        "status": "success",
        "detectadas": detectadas,
        "actualizadas": actualizadas,
        "errores": errores,
        "n": len(actualizadas),
        "hosts_consultados": max(hosts_consultados, len(detectadas) + len(errores)),
    })

@app.route('/api/nodos/wol-todos', methods=['POST'])
@requiere_rol("operator")
def api_nodos_wol_todos():
    """Envía WOL a TODOS los nodos con wol=True en data/nodes.json.
    Paralelizado con timeout corto para no bloquear."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    conf = nodes.todos()
    if not conf:
        return jsonify({"status": "error",
                        "output": "No hay nodos configurados"}), 400

    enviados = []
    omitidos = []
    errores = []

    tareas = []
    for ip, info in conf.items():
        if not info.get("wol"):
            omitidos.append({"ip": ip, "razon": "wol=false"})
            continue
        mac = info.get("mac", "")
        if not mac:
            omitidos.append({"ip": ip, "razon": "sin MAC"})
            continue
        tareas.append((ip, mac))

    def _enviar(item):
        ip, mac = item
        try:
            m = nodes.enviar_wol(ip, mac=mac, timeout=1.0)
            return ("ok", ip, m)
        except Exception as e:
            return ("err", ip, str(e))

    if tareas:
        with ThreadPoolExecutor(max_workers=min(16, len(tareas))) as ex:
            for fut in as_completed(
                    [ex.submit(_enviar, t) for t in tareas], timeout=8):
                try:
                    estado, ip, valor = fut.result()
                except Exception as e:
                    errores.append({"ip": "?", "error": str(e)})
                    continue
                if estado == "ok":
                    enviados.append({"ip": ip, "mac": valor})
                else:
                    errores.append({"ip": ip, "error": valor})

    audit(session.get('usuario'), "power.wol_todos",
          target=str(len(enviados)) + " nodos",
          detalle=",".join(e["ip"] for e in enviados[:15]))

    # Construir salida legible
    lineas = ["Wake-on-LAN a todos los nodos con wol=true", ""]
    lineas.append("Enviados: " + str(len(enviados)))
    for e in enviados:
        lineas.append("  OK  " + e["ip"].ljust(15) + "  " + e["mac"])
    if omitidos:
        lineas.append("")
        lineas.append("Omitidos: " + str(len(omitidos)))
        for o in omitidos:
            lineas.append("  --  " + o["ip"].ljust(15) + "  " + o["razon"])
    if errores:
        lineas.append("")
        lineas.append("Errores: " + str(len(errores)))
        for e in errores:
            lineas.append("  !!  " + e["ip"].ljust(15) + "  " + e["error"])

    return jsonify({
        "status": "success" if not errores else "error",
        "output": "\n".join(lineas),
        "enviados": enviados,
        "omitidos": omitidos,
        "errores": errores,
        "n_enviados": len(enviados),
        "n_omitidos": len(omitidos),
        "n_errores": len(errores),
    })



# ══════════════════════════════════════════════════════════════
# EDITOR DE INVENTARIO
# ══════════════════════════════════════════════════════════════
@app.route('/api/inventory/raw')
@requiere_rol("operator")
def api_inv_raw():
    try:
        return jsonify({
            "status": "success",
            "path": str(inventory_editor.INVENTORY_PATH),
            "contenido": inventory_editor.leer_raw(),
        })
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500


@app.route('/api/inventory/parsed')
@requiere_rol("operator")
def api_inv_parsed():
    try:
        texto = inventory_editor.leer_raw()
        parsed = inventory_editor.parsear(texto)
        ok, errs, warns = inventory_editor.validar(texto)
        return jsonify({
            "status": "success",
            "grupos": parsed["grupos"],
            "orden":  parsed["orden"],
            "valido": ok,
            "errores": errs,
            "warnings": warns,
        })
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500


@app.route('/api/inventory/validate', methods=['POST'])
@requiere_rol("operator")
def api_inv_validate():
    texto = (request.json or {}).get("contenido", "")
    ok, errs, warns = inventory_editor.validar(texto)
    return jsonify({
        "status": "success",
        "valido": ok, "errores": errs, "warnings": warns,
    })


@app.route('/api/inventory/save', methods=['POST'])
@requiere_rol("operator")
def api_inv_save():
    texto = (request.json or {}).get("contenido", "")
    ok, errs, warns = inventory_editor.validar(texto)
    if not ok:
        return jsonify({"status": "error", "output": "Inventario inválido",
                        "errores": errs}), 400
    try:
        bkp = inventory_editor.guardar_raw(texto, usuario=session.get('usuario'))
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "inventory.save",
          detalle="backup=" + (bkp or "sin backup"))
    return jsonify({
        "status": "success",
        "output": "Inventario guardado",
        "backup": bkp,
        "warnings": warns,
    })


@app.route('/api/inventory/nodo', methods=['POST'])
@requiere_rol("operator")
def api_inv_nodo_add():
    d = request.json or {}
    ip = (d.get("ip") or "").strip()
    grupos = d.get("grupos") or []
    vars_ = d.get("vars") or {}
    if not isinstance(grupos, list) or not grupos:
        return jsonify({"status": "error", "output": "Indica al menos un grupo"}), 400
    try:
        texto = inventory_editor.leer_raw()
        nuevo = inventory_editor.añadir_nodo(texto, ip, grupos, vars_)
        ok, errs, _ = inventory_editor.validar(nuevo)
        if not ok:
            return jsonify({"status": "error", "output": "Resultado inválido",
                            "errores": errs}), 400
        bkp = inventory_editor.guardar_raw(nuevo, usuario=session.get('usuario'))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "inventory.nodo_add", target=ip,
          detalle=",".join(grupos))
    return jsonify({"status": "success",
                    "output": f"{ip} añadido a {', '.join(grupos)}",
                    "backup": bkp})


@app.route('/api/inventory/nodo/<path:ip>', methods=['PUT'])
@requiere_rol("operator")
def api_inv_nodo_edit(ip):
    d = request.json or {}
    nuevos_vars = d.get("vars")
    nuevos_grupos = d.get("grupos")  # opcional
    try:
        texto = inventory_editor.leer_raw()
        nuevo = inventory_editor.editar_nodo(texto, ip,
                                             nuevos_vars or {},
                                             nuevos_grupos)
        ok, errs, _ = inventory_editor.validar(nuevo)
        if not ok:
            return jsonify({"status": "error", "output": "Resultado inválido",
                            "errores": errs}), 400
        bkp = inventory_editor.guardar_raw(nuevo, usuario=session.get('usuario'))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "inventory.nodo_edit", target=ip)
    return jsonify({"status": "success", "output": f"{ip} actualizado", "backup": bkp})


@app.route('/api/inventory/nodo/<path:ip>', methods=['DELETE'])
@requiere_rol("operator")
def api_inv_nodo_del(ip):
    try:
        texto = inventory_editor.leer_raw()
        nuevo = inventory_editor.eliminar_nodo(texto, ip)
        ok, errs, _ = inventory_editor.validar(nuevo)
        if not ok:
            return jsonify({"status": "error", "output": "Resultado inválido",
                            "errores": errs}), 400
        bkp = inventory_editor.guardar_raw(nuevo, usuario=session.get('usuario'))
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "inventory.nodo_del", target=ip)
    return jsonify({"status": "success", "output": f"{ip} eliminado", "backup": bkp})


@app.route('/api/inventory/backups')
@requiere_rol("operator")
def api_inv_backups():
    return jsonify({"status": "success",
                    "backups": inventory_editor.listar_backups()})


@app.route('/api/inventory/restore', methods=['POST'])
@requiere_rol("operator")
def api_inv_restore():
    nombre = (request.json or {}).get("nombre", "")
    try:
        inventory_editor.restaurar_backup(nombre)
    except ValueError as e:
        return jsonify({"status": "error", "output": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500
    audit(session.get('usuario'), "inventory.restore", target=nombre)
    return jsonify({"status": "success",
                    "output": f"Inventario restaurado desde {nombre}"})



# ─── Handler de errores: JSON para /api/*, HTML para el resto ───
_json_api_error_handler = True

@app.errorhandler(Exception)
def _api_error_handler(e):
    """Cualquier excepción no capturada en rutas /api/* devuelve JSON."""
    from werkzeug.exceptions import HTTPException
    # Si es HTTPException con código, respetarlo
    if isinstance(e, HTTPException):
        code = e.code or 500
        if request.path.startswith('/api/'):
            return jsonify({
                "status": "error",
                "output": e.description or str(e),
            }), code
        return e

    # Excepción de código — devolver JSON si es API
    if request.path.startswith('/api/'):
        import traceback
        tb = traceback.format_exc()[-800:]
        print(f"[api.error] {request.path}: {e}\n{tb}")
        return jsonify({
            "status": "error",
            "output": f"{type(e).__name__}: {e}",
        }), 500

    # Fuera de /api/* — relanzar
    raise e




# ══════════════════════════════════════════════════════════════
# AUDITORÍA DE USUARIOS (huérfanos, conflictos, etc.)
# ══════════════════════════════════════════════════════════════
@app.route('/api/usuarios/audit')
@requiere_rol("operator")
def api_usuarios_audit():
    """Vista unificada con todas las fuentes."""
    try:
        data = user_admin.inventario_completo()
        return jsonify({"status": "success", **data})
    except Exception as e:
        import traceback
        return jsonify({
            "status": "error",
            "output": str(e),
            "tb": traceback.format_exc()[-400:],
        }), 500


@app.route('/api/usuarios/<username>/purgar', methods=['POST'])
@requiere_admin
def api_usuarios_purgar(username):
    """Purga un usuario de TODAS las fuentes.
    Body: {"modo": "papelera" | "definitivo"}  (default: papelera)
    """
    if not re.fullmatch(r'[a-z][a-z0-9._-]{1,31}', username):
        return jsonify({"status": "error",
                        "output": "Username inválido"}), 400

    body = request.json or {}
    modo = body.get('modo', 'papelera')
    if modo not in ('papelera', 'definitivo'):
        return jsonify({"status": "error",
                        "output": "Modo inválido"}), 400

    # Verificar que no sea el propio usuario del admin
    if username == session.get('usuario'):
        return jsonify({"status": "error",
                        "output": "No puedes purgarte a ti mismo"}), 400

    try:
        resultado = user_admin.purgar_usuario(username, modo=modo)
        audit(session.get('usuario'), f"user.purgar.{modo}",
              target=username,
              detalle=' | '.join(resultado['acciones'])[:400],
              exito=(len(resultado['errores']) == 0))

        status = 'success' if not resultado['errores'] else 'error'
        output = "\n".join(resultado['acciones'])
        if resultado['errores']:
            output += "\n\n⚠ Errores:\n" + "\n".join(resultado['errores'])

        return jsonify({
            "status": status,
            "output": output,
            "modo": modo,
            "username": username,
        })
    except Exception as e:
        return jsonify({"status": "error", "output": str(e)}), 500


# ══════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════
@app.route('/api/health')
def api_health():
    return jsonify({"panel": True, "ts": datetime.now().isoformat()})


# ── Manejo de errores CSRF: en vez de 400, redirige al login ─
from flask_wtf.csrf import CSRFError

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    if request.is_json or request.path.startswith('/api/'):
        return jsonify({"status": "error",
                        "output": "Token CSRF inválido. Recarga la página."}), 400
    # Para páginas normales: redirigir al login con mensaje
    return redirect(url_for('login'))


# ══════════════════════════════════════════════════════════════
# CUENTAS DEL PANEL (login del panel, cifradas)
# ══════════════════════════════════════════════════════════════

# DEPRECATED — eliminado, era confuso con usuarios del clúster
# @app.route('/api/panel-users')
@requiere_admin
def api_panel_users_listar():
    usuarios = credentials.listar_usuarios()
    me = session.get('usuario')
    return jsonify({
        "status": "success",
        "usuarios": [
            {"username": u, "role": info.get("role"), "nombre": info.get("nombre"), "self": u == me}
            for u, info in usuarios.items()
        ]
    })


# @app.route('/api/panel-users', methods=['POST'])
@requiere_admin
def api_panel_users_crear():
    d = request.json or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    role = (d.get("role") or "viewer").strip()
    nombre = (d.get("nombre") or "").strip()

    if not username or len(username) < 3:
        return jsonify({"status": "error", "output": "Usuario muy corto (min 3)"}), 400
    if len(password) < 8:
        return jsonify({"status": "error", "output": "Contraseña minimo 8 caracteres"}), 400
    if role not in ROLES_PANEL:
        return jsonify({"status": "error", "output": "Rol invalido"}), 400

    existentes = credentials.listar_usuarios()
    if username in existentes:
        return jsonify({"status": "error", "output": f"Usuario {username} ya existe"}), 409

    credentials.crear_usuario(username, password, role, nombre)
    audit(session.get('usuario'), "panel_user.create", target=username, detalle=f"role={role}")
    return jsonify({"status": "success", "output": f"Usuario {username} creado con rol {role}"})


# @app.route('/api/panel-users/<username>', methods=['DELETE'])
@requiere_admin
def api_panel_users_eliminar(username):
    me = session.get('usuario')
    if username == me:
        return jsonify({"status": "error", "output": "No puedes eliminarte a ti mismo"}), 400

    if credentials.eliminar_usuario(username):
        audit(me, "panel_user.delete", target=username)
        return jsonify({"status": "success", "output": f"Usuario {username} eliminado"})
    return jsonify({"status": "error", "output": "Usuario no encontrado"}), 404


# @app.route('/api/panel-users/<username>/password', methods=['POST'])
@requiere_admin
def api_panel_users_password(username):
    nueva = (request.json or {}).get("password", "")
    if len(nueva) < 8:
        return jsonify({"status": "error", "output": "Minimo 8 caracteres"}), 400

    if credentials.cambiar_password(username, nueva):
        audit(session.get('usuario'), "panel_user.password", target=username)
        return jsonify({"status": "success", "output": f"Contraseña de {username} actualizada"})
    return jsonify({"status": "error", "output": "Usuario no encontrado"}), 404


# @app.route('/api/panel-users/<username>/role', methods=['POST'])
@requiere_admin
def api_panel_users_role(username):
    me = session.get('usuario')
    if username == me:
        return jsonify({"status": "error", "output": "No puedes cambiarte tu propio rol"}), 400

    nuevo_rol = (request.json or {}).get("role", "")
    if nuevo_rol not in ROLES_PANEL:
        return jsonify({"status": "error", "output": "Rol invalido"}), 400

    info = credentials.obtener_usuario(username)
    if not info:
        return jsonify({"status": "error", "output": "Usuario no encontrado"}), 404

    # Asegurar que quede al menos 1 admin
    usuarios = credentials.listar_usuarios()
    admins_activos = [u for u, i in usuarios.items() if i.get("role") == "admin"]
    if info.get("role") == "admin" and nuevo_rol != "admin" and len(admins_activos) <= 1:
        return jsonify({"status": "error", "output": "Debe quedar al menos 1 admin"}), 400

    creds = credentials.exportar_backup()
    creds[username]["role"] = nuevo_rol
    credentials.importar_backup(creds)

    audit(me, "panel_user.role", target=username, detalle=f"role={nuevo_rol}")
    return jsonify({"status": "success", "output": f"Rol de {username} → {nuevo_rol}"})



tasks.cargar_desde_disco()

# Asegurar que existe la clave SSH maestra del panel
try:
    ssh_panel_keys.asegurar_clave()
except Exception as _e:
    print(f'[startup] no pude generar clave SSH del panel: {_e}')

# WebSocket PTY — shell interactiva
import terminal_ws
terminal_ws.register(app)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=Config.PORT_PANEL,
            debug=False, threaded=True)
