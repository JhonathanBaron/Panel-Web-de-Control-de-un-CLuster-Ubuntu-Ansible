"""
WebSocket → PTY → ssh -tt como EL USUARIO DEL PANEL.

Cada usuario del panel entra como SÍ MISMO en el clúster, con su
propio home, sus permisos y su espacio.

Fallback: si el usuario del panel no existe en el nodo, se usa el
usuario del inventario (comportamiento anterior).
"""
import os, pty, select, signal, struct, fcntl, termios
import json, re, threading
from flask import session, request
from flask_sock import Sock

sock = Sock()

IP_RE   = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')
USER_RE = re.compile(r'^[a-z][a-z0-9._-]{0,31}$')

SSH_OPTS = [
    '-tt',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'LogLevel=ERROR',
    '-o', 'ServerAliveInterval=30',
    '-o', 'ServerAliveCountMax=3',
    '-o', 'PasswordAuthentication=no',   # forzar solo clave pública
    '-o', 'BatchMode=yes',
]

ROLES_PERMITIDOS = {'student', 'operator', 'admin'}


def _audit(usuario, accion, target, detalle="", exito=True):
    try:
        from utils import audit
        audit(usuario, accion, target=target, detalle=detalle, exito=exito)
    except Exception as e:
        print(f"[terminal_ws.audit] {e}")


def _bridge(ws, fd, pid):
    try:
        while True:
            r, _, _ = select.select([fd], [], [], 0.1)
            if fd in r:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                try:
                    ws.send(data.decode('utf-8', 'replace'))
                except Exception:
                    break
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def _resolver_usuario_ssh(usuario_panel, ip):
    """Devuelve (usuario_ssh, usar_clave_maestra, motivo).

    Orden de preferencia:
      1. El propio usuario del panel (juan.vargas)
      2. El ansible_user del inventario (cluster0/cluster1/…)
    """
    # Normalizar
    u = (usuario_panel or '').strip().lower()
    if not USER_RE.match(u):
        u = None

    # ¿Existe como usuario del clúster? (por YAML o /etc/passwd local)
    existe_cluster = False
    if u:
        try:
            import cluster_users
            # Buscar en el combinado
            for usr in cluster_users.listar_combinado().get('users', []):
                if usr.get('username') == u:
                    existe_cluster = True
                    break
        except Exception:
            pass

    if u and existe_cluster:
        return u, True, "usuario del clúster"

    # Fallback: usuario del inventario para ese nodo
    try:
        import inventory
        for n in inventory.resumen_nodos():
            if n.get('ip') == ip:
                inv_user = (n.get('usuario') or '').strip()
                if inv_user:
                    return inv_user, False, "ansible_user del inventario"
    except Exception:
        pass

    return 'cluster0', False, "fallback cluster0"




def _verificar_acceso(ip, usuario_ssh, clave, timeout=3):
    """Prueba un ssh real con la clave maestra. Devuelve True si funciona."""
    try:
        import subprocess
        cmd = [
            'ssh',
            '-i', clave,
            '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=3',
            '-o', 'LogLevel=ERROR',
            f'{usuario_ssh}@{ip}',
            'echo PANEL_SSH_OK',
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 2)
        return r.returncode == 0 and 'PANEL_SSH_OK' in (r.stdout or '')
    except Exception:
        return False


def _distribuir_clave_async(usuario):
    """Lanza la distribución de la clave en un hilo, para no bloquear."""
    def _worker():
        try:
            import ssh_panel_keys
            res, _, _ = ssh_panel_keys.distribuir_a_usuario(usuario, timeout=60)
            n_ok = sum(1 for v in res.values() if v == 'OK')
            print(f"[terminal_ws] clave distribuida a {usuario}: {n_ok} nodos")
        except Exception as e:
            print(f"[terminal_ws] error distribuyendo clave a {usuario}: {e}")
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def _verificar_y_distribuir(ip, usuario_ssh, clave, ws):
    """Comprueba acceso con la clave maestra. Si falla, distribuye la clave
    y reintenta. Devuelve True si al final hay acceso.

    Mientras trabaja, envía mensajes al usuario por el WebSocket.
    """
    if _verificar_acceso(ip, usuario_ssh, clave):
        return True

    # Sin acceso. Avisar al usuario y distribuir.
    msg = (
        f'\r\n\x1b[33m[configurando acceso SSH para {usuario_ssh} '
        f'en {ip}…]\x1b[0m\r\n'
        f'Esto solo ocurre la primera vez. Unos segundos…\r\n'
    )
    try:
        ws.send(msg)
    except Exception:
        pass

    # Distribuir síncronamente pero con timeout corto
    try:
        import ssh_panel_keys
        res, _, _ = ssh_panel_keys.distribuir_a_usuario(usuario_ssh, timeout=60)
        n_ok = sum(1 for v in res.values() if v == 'OK')
        n_nf = sum(1 for v in res.values() if v == 'NOT_FOUND')

        if n_ok == 0 and n_nf == 0:
            try:
                ws.send(
                    '\r\n\x1b[31m[no se pudo distribuir la clave en '
                    'ningún nodo]\x1b[0m\r\n'
                )
            except Exception:
                pass
            return False

        if n_nf > 0:
            try:
                ws.send(
                    f'\r\n\x1b[33m[el usuario {usuario_ssh} no existe en '
                    f'{n_nf} nodo(s)]\x1b[0m\r\n'
                )
            except Exception:
                pass
    except Exception as e:
        try:
            ws.send(f'\r\n\x1b[31m[error distribuyendo clave: {e}]\x1b[0m\r\n')
        except Exception:
            pass
        return False

    # Reintentar hasta 3 veces con delay
    import time
    for intento in range(3):
        time.sleep(1.5)
        if _verificar_acceso(ip, usuario_ssh, clave):
            try:
                ws.send('\r\n\x1b[32m[acceso configurado]\x1b[0m\r\n\r\n')
            except Exception:
                pass
            return True

    try:
        ws.send(
            '\r\n\x1b[31m[no se pudo establecer acceso SSH]\x1b[0m\r\n'
            'Verifica que el usuario existe en el nodo y que el panel '
            'puede escribir en su authorized_keys.\r\n'
        )
    except Exception:
        pass
    return False


def register(app):
    sock.init_app(app)

    @sock.route('/ws/terminal')
    def _ws(ws):
        # ─── 1) Sesión ──────────────────────────────────────
        usuario_panel = session.get('usuario')
        if not usuario_panel:
            try:
                ws.send('\r\n\x1b[31m[no autorizado — recarga la página]\x1b[0m\r\n')
            except Exception:
                pass
            return

        # ─── 2) Rol ─────────────────────────────────────────
        rol = session.get('role', 'viewer')
        try:
            import credentials
            info = credentials.obtener_usuario(usuario_panel) or {}
            rol = info.get('role', rol)
        except Exception:
            pass

        if rol not in ROLES_PERMITIDOS:
            msg = (
                f'\r\n\x1b[31m[acceso denegado]\x1b[0m\r\n'
                f'Tu rol es "{rol}". Se requiere "operator" o "admin".\r\n'
            )
            try:
                ws.send(msg)
            except Exception:
                pass
            _audit(usuario_panel, "terminal.denied",
                   target=request.args.get('ip', '?'),
                   detalle=f"rol={rol}", exito=False)
            return

        # ─── 3) IP ──────────────────────────────────────────
        ip = request.args.get('ip', '').strip()
        if not IP_RE.match(ip):
            try:
                ws.send('\r\n\x1b[31m[IP inválida]\x1b[0m\r\n')
            except Exception:
                pass
            return

        # ─── 4) Resolver usuario SSH ────────────────────────
        usuario_ssh, usar_clave, motivo = _resolver_usuario_ssh(
            usuario_panel, ip)

        # ─── 5) Puerto ──────────────────────────────────────
        try:
            port = int(request.args.get('port', '22'))
            if not (1 <= port <= 65535):
                port = 22
        except Exception:
            port = 22

        # ─── 6) Auditar apertura ────────────────────────────
        _audit(usuario_panel, "terminal.open", target=ip,
               detalle=(f"rol={rol} ssh_user={usuario_ssh} "
                        f"motivo={motivo} clave_maestra={usar_clave}"))

        # ─── 7) Verificar acceso con la clave (auto-distribuir si falta)
        clave_path = None
        if usar_clave:
            try:
                import ssh_panel_keys
                clave_path = ssh_panel_keys.ruta_clave_privada()
                # Verificar y distribuir si hace falta
                if not _verificar_y_distribuir(ip, usuario_ssh, clave_path, ws):
                    # Si no se pudo, intentar con el usuario del inventario
                    fallback, _, _ = _resolver_usuario_ssh('', ip)
                    if fallback != usuario_ssh and _verificar_acceso(ip, fallback, clave_path):
                        usuario_ssh = fallback
                        _audit(usuario_panel, "terminal.fallback",
                               target=ip,
                               detalle=f"usando {fallback} en vez de {usuario_panel}")
                        try:
                            ws.send(
                                f'\r\n\x1b[33m[usando usuario alternativo: '
                                f'{fallback}]\x1b[0m\r\n\r\n'
                            )
                        except Exception:
                            pass
            except Exception as e:
                print(f"[terminal_ws] error preparando clave: {e}")
                usar_clave = False
                clave_path = None

        # ─── 8) Construir comando SSH ───────────────────────
        cmd = ['ssh'] + SSH_OPTS
        if usar_clave and clave_path:
            cmd += ['-i', clave_path]

        if port != 22:
            cmd += ['-p', str(port)]
        cmd += [f'{usuario_ssh}@{ip}']

        # ─── 9) pty.fork + ssh ──────────────────────────────
        pid, fd = pty.fork()

        if pid == 0:
            try:
                os.environ['TERM'] = 'xterm-256color'
                os.environ['COLORTERM'] = 'truecolor'
                os.environ.setdefault('LANG', 'en_US.UTF-8')
                os.environ.setdefault('LC_ALL', 'en_US.UTF-8')
                os.execvp('ssh', cmd)
            except Exception as e:
                try:
                    os.write(2, f'\r\n[exec ssh: {e}]\r\n'.encode())
                except Exception:
                    pass
                os._exit(1)

        threading.Thread(
            target=_bridge, args=(ws, fd, pid), daemon=True
        ).start()

        # ─── 9) Bridge bidireccional ────────────────────────
        try:
            while True:
                msg = ws.receive()
                if msg is None:
                    break

                if isinstance(msg, str) and msg.startswith('\x00'):
                    try:
                        ctrl = json.loads(msg[1:])
                        if ctrl.get('type') == 'resize':
                            cols = max(20, min(500, int(ctrl['cols'])))
                            rows = max(5, min(200, int(ctrl['rows'])))
                            fcntl.ioctl(fd, termios.TIOCSWINSZ,
                                        struct.pack('HHHH', rows, cols, 0, 0))
                    except Exception:
                        pass
                    continue

                if isinstance(msg, str):
                    msg = msg.encode('utf-8', 'replace')
                try:
                    os.write(fd, msg)
                except OSError:
                    break
        except Exception as e:
            print(f"[terminal_ws] {e}")
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

            _audit(usuario_panel, "terminal.close", target=ip,
                   detalle=f"ssh_user={usuario_ssh}")
