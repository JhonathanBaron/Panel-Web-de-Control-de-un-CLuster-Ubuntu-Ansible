"""
Administración avanzada de usuarios del clúster.

Clasifica cada entrada en 5 categorías:
  · ok               → usuario completo y consistente
  · huerfano         → carpeta en NAS sin usuario Linux
  · sin_home         → usuario Linux/YAML sin carpeta en NAS
  · admin_panel      → cuenta del panel sin usuario Linux (normal)
  · sistema          → usuario del SO que cae en el rango por error
"""
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from config import Config


# Usuarios del sistema que hay que IGNORAR aunque caigan en el rango
# de UIDs del clúster (por errores históricos o por instalación)
USUARIOS_IGNORADOS = {
    'nobody', 'nogroup', 'daemon', 'bin', 'sys', 'sync', 'games',
    'man', 'lp', 'mail', 'news', 'uucp', 'proxy', 'www-data',
    'backup', 'list', 'irc', 'gnats', 'systemd-network',
    'systemd-resolve', 'messagebus', 'sshd', 'ntp', 'chrony',
    'netdata', 'ollama', 'redis', 'postgres', 'mysql', 'bash',
    'root', 'sh', 'zsh',
}


# ══════════════════════════════════════════════════════════════
#  Lectura de las 4 fuentes
# ══════════════════════════════════════════════════════════════

def _leer_yaml():
    try:
        import yaml
        with open(Config.USERS_YAML) as f:
            data = yaml.safe_load(f) or {}
        return {u.get('username') for u in data.get('users', [])
                if u.get('username')}
    except Exception:
        return set()


def _leer_panel():
    try:
        import credentials
        return set(credentials.exportar_backup().keys())
    except Exception:
        return set()


def _leer_nas():
    """Lee /srv/nas/home/ vía SSH al NAS. Devuelve {username: {uid, size}}."""
    resultado = {}
    try:
        nas_ip = getattr(Config, 'NAS_IP', '10.4.8.19')
        nas_user = getattr(Config, 'NAS_SSH_USER', 'cluster9')
        base = getattr(Config, 'NAS_BASE', '/srv/nas/home-panel')
        home_real = str(Path(base).parent / 'home')

        cmd = [
            'ssh',
            '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=5',
            '-o', 'LogLevel=ERROR',
            f'{nas_user}@{nas_ip}',
            f"sudo ls -lan {home_real}/ 2>/dev/null"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        for line in (r.stdout or '').splitlines():
            partes = line.split()
            if len(partes) < 9 or not partes[0].startswith('d'):
                continue
            uid = partes[2]
            nombre = partes[8] if len(partes) == 9 else partes[-1]
            if nombre in ('.', '..'):
                continue
            if not re.match(r'^[a-z][a-z0-9._-]+$', nombre):
                continue
            if nombre in USUARIOS_IGNORADOS:
                continue
            if uid == '0':
                continue

            # Tamaño del home
            size = 0
            try:
                cmd2 = [
                    'ssh', '-o', 'BatchMode=yes',
                    '-o', 'StrictHostKeyChecking=no',
                    '-o', 'UserKnownHostsFile=/dev/null',
                    '-o', 'ConnectTimeout=5',
                    '-o', 'LogLevel=ERROR',
                    f'{nas_user}@{nas_ip}',
                    f"sudo du -sb {home_real}/{nombre} 2>/dev/null | cut -f1"
                ]
                r2 = subprocess.run(
                    cmd2, capture_output=True, text=True, timeout=10)
                size = int((r2.stdout or '0').strip() or 0)
            except Exception:
                pass

            resultado[nombre] = {
                'uid': int(uid) if uid.isdigit() else 0,
                'size': size,
            }
    except Exception as e:
        print(f"[user_admin] error leyendo NAS: {e}")
    return resultado


def _leer_usuarios_linux():
    """Lee usuarios Linux del clúster vía ansible.

    Filtros estrictos:
      · uid 20000-49999
      · home bajo /srv/nas/home/ o bajo el NAS_BASE
      · excluye usuarios del sistema conocidos
    """
    from utils import run_remote_script_multi

    resultado = {}
    try:
        # Filtrar por home en /srv/nas — es lo que define "usuario del clúster"
        script = (
            "getent passwd | awk -F: "
            "'$3 >= 20000 && $3 <= 49999 && $6 ~ /srv\\/nas/ "
            "{print $1 \":\" $3 \":\" $6}'"
        )
        por_host = run_remote_script_multi(
            'cluster', script, become=False, timeout=30)

        for host, data in por_host.items():
            if host.startswith('_'):
                continue
            stdout = (data.get('stdout') or '').replace('\r', '')
            for linea in stdout.splitlines():
                linea = linea.strip()
                if not linea:
                    continue
                partes = linea.split(':')
                if len(partes) < 3:
                    continue
                user, uid, home = partes[0], partes[1], partes[2]

                # Filtro de seguridad
                if not user or user in USUARIOS_IGNORADOS:
                    continue
                if not re.match(r'^[a-z][a-z0-9._-]{1,31}$', user):
                    continue
                if user in resultado:
                    continue

                resultado[user] = {
                    'uid': int(uid) if uid.isdigit() else 0,
                    'home': home,
                }
    except Exception as e:
        print(f"[user_admin] error leyendo passwd: {e}")

    return resultado


# ══════════════════════════════════════════════════════════════
#  Análisis
# ══════════════════════════════════════════════════════════════

def _clasificar(u, en_yaml, en_panel, en_nas, en_linux):
    """Devuelve el estado del usuario."""
    # Usuario del sistema — ni siquiera debería estar aquí
    if u in USUARIOS_IGNORADOS:
        return 'sistema'

    # Cuenta del panel sin usuario Linux → normal, es el admin del panel
    if en_panel and not en_linux and not en_nas:
        return 'admin_panel'

    # Todo está
    if en_yaml and en_panel and en_nas and en_linux:
        return 'ok'

    # Carpeta en NAS pero sin usuario Linux ni YAML → huérfano claro
    if en_nas and not en_linux and not en_yaml:
        return 'huerfano'

    # En YAML + Linux pero sin carpeta NAS → falta crear el home
    if en_yaml and en_linux and not en_nas:
        return 'sin_home'

    # En Linux pero no en YAML → pendiente importar
    if en_linux and not en_yaml:
        return 'pendiente_importar'

    # En YAML pero no en Linux → pendiente aplicar
    if en_yaml and not en_linux:
        return 'pendiente_aplicar'

    return 'parcial'


def inventario_completo():
    """Vista unificada con todas las fuentes y anomalías."""
    yaml_set = _leer_yaml()
    panel_set = _leer_panel()
    nas_dict = _leer_nas()
    linux_dict = _leer_usuarios_linux()

    todos = yaml_set | panel_set | set(nas_dict.keys()) | set(linux_dict.keys())

    # UID → usuarios (para detectar conflictos)
    uid_map = {}
    for u in todos:
        for fuente in (nas_dict, linux_dict):
            if u in fuente:
                uid = fuente[u].get('uid', 0)
                if uid > 0:
                    uid_map.setdefault(uid, set()).add(u)
                    break

    conflictos_uid = {
        uid: sorted(users)
        for uid, users in uid_map.items()
        if len(users) > 1
    }

    usuarios = []
    for u in sorted(todos):
        # Ignorar usuarios del sistema explícitamente
        if u in USUARIOS_IGNORADOS:
            continue

        en_yaml = u in yaml_set
        en_panel = u in panel_set
        en_nas = u in nas_dict
        en_linux = u in linux_dict

        estado = _clasificar(u, en_yaml, en_panel, en_nas, en_linux)

        # UID
        uid = None
        if en_nas:
            uid = nas_dict[u]['uid']
        elif en_linux:
            uid = linux_dict[u]['uid']

        tiene_conflicto = bool(uid and uid in conflictos_uid)

        # ¿Se puede purgar? Solo para huérfanos claros
        puede_purgar = estado == 'huerfano'

        # ¿Se puede reparar? Solo si falta home
        puede_reparar = estado == 'sin_home'

        usuarios.append({
            'username': u,
            'uid': uid,
            'en_yaml': en_yaml,
            'en_panel': en_panel,
            'en_nas': en_nas,
            'en_linux': en_linux,
            'estado': estado,
            'tiene_conflicto_uid': tiene_conflicto,
            'conflicto_con': sorted(
                [x for x in conflictos_uid.get(uid, []) if x != u]
            ) if tiene_conflicto else [],
            'size_bytes': nas_dict[u]['size'] if en_nas else 0,
            'puede_purgar': puede_purgar,
            'puede_reparar': puede_reparar,
        })

    # Resumen
    resumen = {
        'total': len(usuarios),
        'ok': sum(1 for u in usuarios if u['estado'] == 'ok'),
        'huerfanos': sum(1 for u in usuarios if u['estado'] == 'huerfano'),
        'sin_home': sum(1 for u in usuarios if u['estado'] == 'sin_home'),
        'admin_panel': sum(1 for u in usuarios if u['estado'] == 'admin_panel'),
        'pendiente_aplicar': sum(1 for u in usuarios if u['estado'] == 'pendiente_aplicar'),
        'pendiente_importar': sum(1 for u in usuarios if u['estado'] == 'pendiente_importar'),
        'conflictos_uid': len(conflictos_uid),
    }

    return {
        'usuarios': usuarios,
        'resumen': resumen,
        'conflictos_uid': conflictos_uid,
    }


# ══════════════════════════════════════════════════════════════
#  Purgar
# ══════════════════════════════════════════════════════════════

def purgar_usuario(username, modo='papelera'):
    """Elimina COMPLETAMENTE un usuario de las 4 fuentes."""
    acciones = []
    errores = []

    if not re.match(r'^[a-z][a-z0-9._-]{1,31}$', username):
        raise ValueError(f'Username inválido: {username}')

    if username in USUARIOS_IGNORADOS:
        raise ValueError(f'No se puede purgar un usuario del sistema: {username}')

    # 1) users.yaml
    try:
        from utils import leer_usuarios, guardar_usuarios
        data = leer_usuarios()
        antes = len(data.get('users', []))
        data['users'] = [u for u in data.get('users', [])
                         if u.get('username') != username]
        if len(data['users']) < antes:
            guardar_usuarios(data)
            acciones.append('✓ Eliminado de users.yaml')
        else:
            acciones.append('· No estaba en users.yaml')
    except Exception as e:
        errores.append(f'users.yaml: {e}')

    # 2) /etc/passwd
    try:
        from utils import run_safe
        script = (
            f"pkill -u {username} 2>/dev/null; "
            f"sleep 1; "
            f"userdel -r {username} 2>/dev/null || userdel {username} 2>/dev/null; "
            f"if id {username} >/dev/null 2>&1; then echo BORRADO=no; "
            f"else echo BORRADO=si; fi"
        )
        cmd = ['ansible', 'cluster', '-i', Config.INVENTORY,
               '-b', '-m', 'shell', '-a', script]
        rc, out, _ = run_safe(cmd, timeout=120, cwd=Config.ANSIBLE_DIR)
        n_ok = (out or '').count('BORRADO=si')
        n_no = (out or '').count('BORRADO=no')
        if n_ok > 0:
            acciones.append(
                f'✓ Eliminado del clúster ({n_ok} nodos, {n_no} con error)')
        else:
            acciones.append('· No estaba en /etc/passwd')
    except Exception as e:
        errores.append(f'userdel: {e}')

    # 3) Carpeta NAS
    try:
        nas_ip = getattr(Config, 'NAS_IP', '10.4.8.19')
        nas_user = getattr(Config, 'NAS_SSH_USER', 'cluster9')
        base = str(Path(getattr(Config, 'NAS_BASE', '/srv/nas/home')).parent / 'home')
        carpeta = f'{base}/{username}'

        fecha = datetime.now().strftime("%Y%m%d")
        hora = datetime.now().strftime("%H%M%S")

        if modo == 'papelera':
            papelera = f'{base}/.papelera-{fecha}'
            sufijo = f'{username}.{hora}'
            script = (
                f"if [ -d '{carpeta}' ]; then "
                f"  sudo mkdir -p '{papelera}'; "
                f"  sudo mv '{carpeta}' '{papelera}/{sufijo}'; "
                f"  echo MOVIDO=si; "
                f"else echo MOVIDO=no; fi"
            )
        else:
            script = (
                f"if [ -d '{carpeta}' ]; then "
                f"  sudo rm -rf '{carpeta}'; echo BORRADO=si; "
                f"else echo BORRADO=no; fi"
            )

        cmd = ['ssh',
               '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=no',
               '-o', 'UserKnownHostsFile=/dev/null',
               '-o', 'ConnectTimeout=8',
               '-o', 'LogLevel=ERROR',
               f'{nas_user}@{nas_ip}', script]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (r.stdout or '').strip()
        if 'SI' in out.upper():
            if modo == 'papelera':
                acciones.append('✓ Carpeta movida a papelera')
            else:
                acciones.append('✓ Carpeta borrada definitivamente')
        else:
            acciones.append('· No tenía carpeta en el NAS')
    except Exception as e:
        errores.append(f'NAS: {e}')

    # 4) Credenciales del panel
    try:
        import credentials
        if credentials.tiene_hash(username):
            credentials.eliminar_usuario(username)
            acciones.append('✓ Credenciales del panel eliminadas')
        else:
            acciones.append('· No estaba en el panel')
    except Exception as e:
        errores.append(f'panel: {e}')

    # 5) Cuota
    try:
        nas_ip = getattr(Config, 'NAS_IP', '10.4.8.19')
        nas_user = getattr(Config, 'NAS_SSH_USER', 'cluster9')
        cmd = ['ssh',
               '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=no',
               '-o', 'UserKnownHostsFile=/dev/null',
               '-o', 'ConnectTimeout=5',
               '-o', 'LogLevel=ERROR',
               f'{nas_user}@{nas_ip}',
               f"sudo setquota -u {username} 0 0 0 0 / 2>&1 || true"]
        subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        acciones.append('✓ Cuota liberada')
    except Exception:
        pass

    return {
        'username': username,
        'acciones': acciones,
        'errores': errores,
        'modo': modo,
    }
