import subprocess
import yaml
import json
import re
import os
import tempfile
import ipaddress
from datetime import datetime
from pathlib import Path
from config import Config


# ── Ejecución segura ─────────────────────────────────────────
def run_safe(cmd_list, timeout=60, cwd=None):
    if not isinstance(cmd_list, list):
        raise ValueError("cmd_list debe ser lista, no string")
    try:
        res = subprocess.run(cmd_list, capture_output=True, text=True,
                             timeout=timeout, cwd=cwd)
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout después de {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def run_ansible(target, module, args="", become=False, timeout=30):
    cmd = ["ansible", target, "-i", Config.INVENTORY]
    if become:
        cmd.append("-b")
    cmd += ["-m", module]
    if args:
        cmd += ["-a", args]
    return run_safe(cmd, timeout=timeout, cwd=Config.ANSIBLE_DIR)


def run_playbook(playbook_name, timeout=900):
    path = str(Path(Config.PLAYBOOKS) / playbook_name)
    cmd = ["ansible-playbook", "-i", Config.INVENTORY, path]
    return run_safe(cmd, timeout=timeout, cwd=Config.ANSIBLE_DIR)


def run_remote_script(target, script_content, become=False, timeout=30):
    """
    Ejecuta un script bash en un nodo remoto via ansible.
    Devuelve SOLO el stdout del script, parseando el JSON de Ansible.
    """
    full_content = "#!/bin/bash\n" + script_content

    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(full_content)
        script_path = f.name
    os.chmod(script_path, 0o755)

    try:
        env = os.environ.copy()
        env["ANSIBLE_STDOUT_CALLBACK"] = "json"
        # ANSIBLE_CALLBACKS_ENABLED vacío rompe en Ansible 2.20 (ValueError: non-empty plugin name)
        env["ANSIBLE_LOAD_CALLBACK_PLUGINS"] = "True"
        env["ANSIBLE_DISPLAY_SKIPPED_HOSTS"] = "False"
        env["ANSIBLE_DISPLAY_OK_HOSTS"] = "False"

        cmd = ["ansible", target, "-i", Config.INVENTORY]
        if become:
            cmd.append("-b")
        cmd += ["-m", "script", "-a", script_path]

        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, cwd=Config.ANSIBLE_DIR, env=env)

        stdout_text = ""
        stderr_text = ""
        rc = res.returncode

        # Extraer JSON del output: buscar el primer '{' y usar raw_decode
        try:
            raw = res.stdout
            idx = raw.find("{")
            if idx >= 0:
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(raw[idx:])

                # Recorrer el formato de ansible json callback
                for play in data.get("plays", []):
                    for task in play.get("tasks", []):
                        for host_name, host_data in task.get("hosts", {}).items():
                            if "stdout" in host_data:
                                stdout_text = host_data["stdout"]
                                stderr_text = host_data.get("stderr", "")
                                rc = host_data.get("rc", 0)
                                break
        except Exception as e:
            # Fallback: devolver stdout crudo
            stdout_text = res.stdout
            stderr_text = res.stderr

        return rc, stdout_text, stderr_text

    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


# ── Validadores ──────────────────────────────────────────────
def validar_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except (ValueError, TypeError):
        return False


def validar_username(u):
    return bool(re.fullmatch(r"[a-z][a-z0-9._-]{2,31}", u or ""))


# ── Usuarios ─────────────────────────────────────────────────
def leer_usuarios():
    try:
        with open(Config.USERS_YAML) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        return {"users": [], "config": {}, "error": str(e)}


def guardar_usuarios(data):
    with open(Config.USERS_YAML, 'w') as f:
        yaml.safe_dump(data, f, default_flow_style=False,
                       sort_keys=False, allow_unicode=True)


# ── Auditoría ────────────────────────────────────────────────
def audit(usuario, accion, detalle="", target="", exito=True):
    try:
        Path(Config.AUDIT_LOG).parent.mkdir(exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "usuario": usuario,
            "accion": accion,
            "target": target,
            "detalle": str(detalle)[:500],
            "exito": exito
        }
        with open(Config.AUDIT_LOG, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[audit] error: {e}")


def leer_audit(limite=200, filtro_usuario=None, filtro_accion=None):
    path = Path(Config.AUDIT_LOG)
    if not path.exists():
        return []
    lineas = path.read_text().strip().split("\n")
    entries = []
    for l in reversed(lineas):
        if not l.strip():
            continue
        try:
            e = json.loads(l)
            if filtro_usuario and e.get("usuario") != filtro_usuario:
                continue
            if filtro_accion and e.get("accion") != filtro_accion:
                continue
            entries.append(e)
            if len(entries) >= limite:
                break
        except Exception:
            continue
    return entries



def run_remote_script_multi(target, script_content, become=False, timeout=30):
    """Como run_remote_script pero devuelve dict {host: {rc, stdout, stderr}}
    para TODOS los hosts del target. Soporta grupos, 'all', o IPs."""
    full_content = "#!/bin/bash\n" + script_content

    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(full_content)
        script_path = f.name
    os.chmod(script_path, 0o755)

    try:
        env = os.environ.copy()
        env["ANSIBLE_STDOUT_CALLBACK"] = "json"
        # ANSIBLE_CALLBACKS_ENABLED vacío rompe en Ansible 2.20
        env["ANSIBLE_LOAD_CALLBACK_PLUGINS"] = "True"
        env["ANSIBLE_DISPLAY_SKIPPED_HOSTS"] = "False"
        env["ANSIBLE_DISPLAY_OK_HOSTS"] = "False"

        cmd = ["ansible", target, "-i", Config.INVENTORY]
        if become:
            cmd.append("-b")
        cmd += ["-m", "script", "-a", script_path]

        res = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=Config.ANSIBLE_DIR, env=env)

        resultado = {}
        try:
            raw = res.stdout
            idx = raw.find("{")
            if idx >= 0:
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(raw[idx:])

                for play in data.get("plays", []):
                    for task in play.get("tasks", []):
                        for host_name, host_data in task.get("hosts", {}).items():
                            if "stdout" in host_data or "rc" in host_data:
                                resultado[host_name] = {
                                    "rc":     host_data.get("rc", 0),
                                    "stdout": host_data.get("stdout", ""),
                                    "stderr": host_data.get("stderr", ""),
                                }
                            elif "msg" in host_data:
                                resultado[host_name] = {
                                    "rc":     host_data.get("rc", 255),
                                    "stdout": "",
                                    "stderr": host_data.get("msg", "sin respuesta"),
                                }
        except Exception as e:
            resultado["_parse_error"] = {
                "rc": -1,
                "stdout": res.stdout[:2000],
                "stderr": f"parse: {e} | stderr: {res.stderr[:500]}",
            }

        return resultado
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass
