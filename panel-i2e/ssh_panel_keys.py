"""
Gestión de la clave SSH maestra del panel.

El panel usa una clave SSH dedicada para autenticarse como CUALQUIER
usuario del clúster. La clave pública se distribuye a los
authorized_keys de cada usuario en cada nodo.

Seguridad:
  · Clave privada en data/ssh_panel_key (chmod 600)
  · Clave pública en data/ssh_panel_key.pub
  · No se usa passphrase (necesario para automatización)
  · Si la clave se filtra, hay que rotar en todos los nodos
"""
import re
import os
import subprocess
from pathlib import Path

from config import Config

_DATA_DIR = Path(Config.DATA_DIR)
_PRIV = _DATA_DIR / "ssh_panel_key"
_PUB  = _DATA_DIR / "ssh_panel_key.pub"


# ─── Generación ────────────────────────────────────────────────
def asegurar_clave():
    """Genera la clave si no existe. Devuelve (priv_path, pub_text)."""
    _DATA_DIR.mkdir(exist_ok=True, parents=True)

    if not _PRIV.exists():
        print("[ssh_panel_keys] generando clave nueva…")
        r = subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "",
             "-f", str(_PRIV), "-C", "panel-i2e@cluster"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            raise RuntimeError(f"ssh-keygen falló: {r.stderr}")
        try:
            _PRIV.chmod(0o600)
            _PUB.chmod(0o644)
        except Exception:
            pass

    if not _PUB.exists():
        raise RuntimeError("clave pública no encontrada tras generar")

    # Re-aplicar permisos SIEMPRE (el restore desde backup puede dejarlos mal)
    try:
        _PRIV.chmod(0o600)
        _PUB.chmod(0o644)
    except Exception:
        pass

    pub_text = _PUB.read_text().strip()
    return _PRIV, pub_text


def ruta_clave_privada():
    """Devuelve el path de la clave privada, generándola si hace falta."""
    if not _PRIV.exists():
        asegurar_clave()
    return str(_PRIV)


def clave_publica():
    """Devuelve el texto de la clave pública."""
    if not _PUB.exists():
        asegurar_clave()
    return _PUB.read_text().strip()


# ─── Distribución ──────────────────────────────────────────────
def _script_distribuir(usuario, pub_key):
    """Script bash que se ejecuta en cada nodo para añadir la clave
    al usuario indicado (si existe)."""
    # Escapamos la clave para meterla en single quotes en el shell remoto
    pub_esc = pub_key.replace("'", "'\\''")
    usuario_esc = usuario.replace("'", "")
    return (
        f"U='{usuario_esc}'; "
        f"if id \"$U\" >/dev/null 2>&1; then "
        f"  HOME_U=$(getent passwd \"$U\" | cut -d: -f6); "
        f"  if [ -z \"$HOME_U\" ]; then exit 0; fi; "
        f"  mkdir -p \"$HOME_U/.ssh\" 2>/dev/null || exit 0; "
        f"  chmod 700 \"$HOME_U/.ssh\"; "
        f"  touch \"$HOME_U/.ssh/authorized_keys\"; "
        f"  if ! grep -qF '{pub_esc}' \"$HOME_U/.ssh/authorized_keys\"; then "
        f"    echo '{pub_esc}' >> \"$HOME_U/.ssh/authorized_keys\"; "
        f"  fi; "
        f"  chmod 600 \"$HOME_U/.ssh/authorized_keys\"; "
        f"  chown -R \"$U\":\"$U\" \"$HOME_U/.ssh\" 2>/dev/null || true; "
        f"  echo OK; "
        f"else "
        f"  echo NOT_FOUND; "
        f"fi"
    )


def distribuir_a_usuario(usuario, timeout=120):
    """Distribuye la clave pública al usuario en todos los nodos.

    Usa el módulo authorized_key de Ansible con --become-user, para que
    el módulo se ejecute COMO el usuario destino (no como root). Esto
    es imprescindible cuando el home está en NFS con root_squash.

    Devuelve (resultado_dict, rc, salida_completa).
    """
    import json
    import tempfile
    from utils import run_safe

    _, pub = asegurar_clave()
    pub = pub.strip()

    # Escribimos las vars en un archivo temporal para evitar escapes
    # problemáticos con +/= en la pubkey
    with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False) as tf:
        json.dump({"panel_pubkey": pub}, tf)
        vars_file = tf.name

    try:
        cmd = [
            "ansible", "cluster",
            "-i", Config.INVENTORY,
            "-b",                                # become
            "--become-user", usuario,            # become como el usuario
            "-m", "authorized_key",
            "-a", f"user={usuario} key={{{{ panel_pubkey }}}} state=present",
            "-e", f"@{vars_file}",
            "-o",
        ]

        rc, out, err = run_safe(
            cmd, timeout=timeout, cwd=Config.ANSIBLE_DIR)
    finally:
        try:
            import os
            os.unlink(vars_file)
        except Exception:
            pass

    resultado = {}
    for linea in (out or "").splitlines():
        linea = linea.replace("\r", "").strip()
        if "|" not in linea:
            continue

        # Formato: "10.4.8.11 | CHANGED => {...}"
        # o:        "10.4.8.11 | SUCCESS => {...}"
        # o:        "10.4.8.11 | FAILED! => {...}"
        # o:        "10.4.8.11 | UNREACHABLE! => {...}"
        m = re.match(
            r"^(\d+\.\d+\.\d+\.\d+)\s*\|\s*"
            r"(SUCCESS|CHANGED|FAILED!?|UNREACHABLE!?)\s*(?:=>|\|)?\s*(.*)$",
            linea, re.IGNORECASE)
        if not m:
            continue

        ip = m.group(1)
        estado = m.group(2).upper().rstrip("!")
        detalle = (m.group(3) or "").lower()

        if estado in ("SUCCESS", "CHANGED"):
            resultado[ip] = "OK"
        elif estado == "UNREACHABLE":
            resultado[ip] = "ERROR"
        elif estado == "FAILED":
            # ¿Es porque el usuario no existe o porque el directorio ya está?
            if any(kw in detalle for kw in (
                    "no such user", "user does not exist",
                    "does not exist", "unknown user",
                    "user not found")):
                resultado[ip] = "NOT_FOUND"
            elif "file exists" in detalle:
                # El directorio existe pero no se puede escribir → tratarlo
                # como OK tentativo y verificar más tarde
                resultado[ip] = "OK"
            else:
                resultado[ip] = "ERROR"

    return resultado, rc, (out or "") + "\n" + (err or "")


def verificar_acceso(ip, usuario, timeout=4):
    """Prueba un ssh real con la clave maestra como el usuario.
    Devuelve True si funciona."""
    import subprocess
    try:
        clave = ruta_clave_privada()
        cmd = [
            "ssh",
            "-i", clave,
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=3",
            "-o", "LogLevel=ERROR",
            f"{usuario}@{ip}",
            "echo PANEL_OK",
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0 and "PANEL_OK" in (r.stdout or "")
    except Exception:
        return False
