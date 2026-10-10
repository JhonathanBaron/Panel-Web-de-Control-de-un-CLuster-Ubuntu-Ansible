"""
Cliente SSH directo — reemplaza Ansible para lecturas de recursos.
Ansible tarda ~200ms de arranque por proceso; SSH puro ~15ms.
Soporta ejecución en paralelo.
"""
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from config import Config
    _DEFAULT_USER = getattr(Config, 'SSH_USER', 'cluster0')
except Exception:
    _DEFAULT_USER = 'cluster0'

_SSH_OPTS = [
    '-o', 'BatchMode=yes',           # no pedir password
    '-o', 'ConnectTimeout=3',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'LogLevel=ERROR',
    '-o', 'ServerAliveInterval=15',
    '-o', 'ServerAliveCountMax=2',
]


def run_ssh(ip, command, user=_DEFAULT_USER, timeout=6):
    """Ejecuta un comando por SSH directo.
    Devuelve (rc, stdout, stderr)."""
    cmd = ['ssh'] + _SSH_OPTS + [f'{user}@{ip}', command]
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, '', f'timeout {timeout}s'
    except Exception as e:
        return -1, '', str(e)


def run_ssh_parallel(ips, command, user=_DEFAULT_USER,
                     timeout=6, max_workers=16):
    """Ejecuta el mismo comando en varios nodos en paralelo.
    Devuelve dict {ip: (rc, stdout, stderr)}."""
    def _one(ip):
        rc, out, err = run_ssh(ip, command, user=user, timeout=timeout)
        return ip, rc, out, err

    resultado = {}
    ips = list(ips)
    if not ips:
        return resultado

    with ThreadPoolExecutor(max_workers=min(max_workers, len(ips))) as ex:
        futuros = {ex.submit(_one, ip): ip for ip in ips}
        for fut in as_completed(futuros, timeout=timeout + 4):
            try:
                ip, rc, out, err = fut.result()
                resultado[ip] = (rc, out, err)
            except Exception as e:
                ip = futuros[fut]
                resultado[ip] = (-1, '', str(e))

    # Rellenar los que no respondieron
    for ip in ips:
        if ip not in resultado:
            resultado[ip] = (-1, '', 'sin respuesta')

    return resultado
