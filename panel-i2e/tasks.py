"""
Sistema de tareas en background.
- Lanza comandos en hilos daemon
- Acumula salida línea por línea (para streaming por polling)
- Persiste a disco para sobrevivir reinicios
"""
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from config import Config

_TASKS = {}
_LOCK = threading.Lock()
_MAX_TASKS = 100
_TASKS_DIR = Path(Config.DATA_DIR) / "tasks"


def _ahora():
    return datetime.now().isoformat(timespec="seconds")


class Task:
    def __init__(self, kind, cmd, cwd, timeout, meta=None):
        self.id        = uuid.uuid4().hex[:12]
        self.kind      = kind
        self.cmd       = cmd
        self.cwd       = cwd
        self.timeout   = timeout
        self.meta      = meta or {}
        self.usuario   = self.meta.get("usuario")
        self.nombre    = self.meta.get("nombre")
        self.status    = "running"      # running | ok | error | timeout
        self.rc        = None
        self.output    = ""
        self.lines     = []             # [{"t": iso, "txt": str}, ...]
        self.started   = _ahora()
        self.finished  = None

    def to_dict(self, with_output=True, since=0):
        d = {
            "id":       self.id,
            "kind":     self.kind,
            "nombre":   self.nombre,
            "usuario":  self.usuario,
            "status":   self.status,
            "rc":       self.rc,
            "started":  self.started,
            "finished": self.finished,
            "meta":     self.meta,
            "n_lines":  len(self.lines),
        }
        if with_output:
            d["output"] = self.output
            d["lines"]  = self.lines[since:] if since else self.lines
        return d


def _persistir(task):
    try:
        _TASKS_DIR.mkdir(parents=True, exist_ok=True)
        p = _TASKS_DIR / f"{task.id}.json"
        p.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[tasks] no se pudo persistir {task.id}: {e}")


def _limpiar_viejas():
    """Mantiene el dict por debajo del límite."""
    if len(_TASKS) <= _MAX_TASKS:
        return
    terminadas = [(k, v) for k, v in _TASKS.items() if v.status != "running"]
    terminadas.sort(key=lambda kv: kv[1].started)
    sobran = len(_TASKS) - _MAX_TASKS
    for k, _ in terminadas[:sobran]:
        _TASKS.pop(k, None)


def _run(task):
    try:
        proc = subprocess.Popen(
            task.cmd, cwd=task.cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        inicio = time.time()
        for line in proc.stdout:
            if time.time() - inicio > task.timeout:
                try: proc.kill()
                except Exception: pass
                task.status = "timeout"
                task.rc = -1
                msg = f"\n[timeout después de {task.timeout}s]"
                task.output += msg
                task.lines.append({"t": _ahora(), "txt": msg.strip()})
                break
            task.output += line
            task.lines.append({"t": _ahora(), "txt": line.rstrip("\n")})
        rc = proc.wait()
        if task.status == "running":
            task.rc = rc
            task.status = "ok" if rc == 0 else "error"
    except Exception as e:
        task.status = "error"
        task.rc = -1
        msg = f"[exception] {e}"
        task.output += "\n" + msg
        task.lines.append({"t": _ahora(), "txt": msg})
    finally:
        task.finished = _ahora()
        _persistir(task)


def lanzar(kind, cmd, cwd, timeout, meta=None):
    task = Task(kind, cmd, cwd, timeout, meta or {})
    with _LOCK:
        _limpiar_viejas()
        _TASKS[task.id] = task
    hilo = threading.Thread(target=_run, args=(task,), daemon=True)
    hilo.start()
    return task


def obtener(task_id):
    with _LOCK:
        return _TASKS.get(task_id)


def listar(limit=30, solo_usuario=None):
    with _LOCK:
        tareas = list(_TASKS.values())
    if solo_usuario:
        tareas = [t for t in tareas if t.usuario == solo_usuario]
    tareas.sort(key=lambda t: t.started, reverse=True)
    return tareas[:limit]


def cargar_desde_disco():
    """Carga tareas recientes al arrancar el panel."""
    if not _TASKS_DIR.exists():
        return
    archivos = sorted(_TASKS_DIR.glob("*.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    for f in archivos:
        try:
            data = json.loads(f.read_text())
            t = Task(data["kind"], [], None, 0, data.get("meta") or {})
            t.id       = data["id"]
            t.nombre   = data.get("nombre")
            t.usuario  = data.get("usuario")
            # Tareas que quedaron en running tras un reinicio → error
            t.status   = "error" if data["status"] == "running" else data["status"]
            t.rc       = data.get("rc")
            t.started  = data["started"]
            t.finished = data.get("finished") or data["started"]
            t.output   = data.get("output", "")
            t.lines    = data.get("lines", [])
            with _LOCK:
                _TASKS[t.id] = t
        except Exception:
            continue


# ═══════════════════════════════════════════════════════════════
# Limpieza de tareas
# ═══════════════════════════════════════════════════════════════
def eliminar(task_id):
    """Elimina una tarea terminada. Devuelve True si se eliminó."""
    with _LOCK:
        t = _TASKS.get(task_id)
        if not t:
            return False
        if t.status == "running":
            raise ValueError("No se puede eliminar una tarea en ejecución")
        _TASKS.pop(task_id, None)
    # Borrar del disco
    try:
        f = _TASKS_DIR / f"{task_id}.json"
        if f.exists():
            f.unlink()
    except Exception:
        pass
    return True


def limpiar(status=None):
    """Elimina tareas terminadas. `status` opcional: 'error', 'ok',
    'timeout'. Sin status → todas las terminadas.
    Devuelve el número de tareas eliminadas."""
    with _LOCK:
        a_borrar = []
        for tid, t in _TASKS.items():
            if t.status == "running":
                continue
            if status is None or t.status == status:
                a_borrar.append(tid)
        for tid in a_borrar:
            _TASKS.pop(tid, None)

    # Borrar archivos
    for tid in a_borrar:
        try:
            f = _TASKS_DIR / f"{tid}.json"
            if f.exists():
                f.unlink()
        except Exception:
            pass

    return len(a_borrar)
