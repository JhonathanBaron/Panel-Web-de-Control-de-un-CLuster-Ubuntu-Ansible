"""
Navegador del NAS — /srv/nas/home/<usuario>
Seguridad: bloquea path traversal, symlinks fuera del home, etc.
"""
import re
import csv
import io
import json
import mimetypes
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from config import Config

NAS_BASE = Path(Config.NAS_BASE)


# ─── Sanitización ────────────────────────────────────────────
def _limpiar_rel(rel):
    """Convierte la ruta relativa entrante a una forma segura."""
    if rel is None:
        return ""
    if "\x00" in rel:
        raise ValueError("byte nulo en la ruta")
    rel = rel.replace(chr(92), "/").strip().strip("/")
    partes = [p for p in rel.split("/") if p and p != "."]
    for p in partes:
        if p == "..":
            raise ValueError("'..' no permitido")
    return "/".join(partes)


def _limpiar_nombre(nombre):
    if not nombre:
        raise ValueError("nombre vacío")
    nombre = nombre.strip()
    if len(nombre) > 200:
        raise ValueError("nombre demasiado largo")
    if "/" in nombre or "\x00" in nombre:
        raise ValueError("nombre contiene caracteres no permitidos")
    if nombre in (".", ".."):
        raise ValueError("nombre reservado")
    return nombre


def _normalizar_usuario(usuario):
    """Normaliza el nombre de usuario para la carpeta del NAS.
    - minúsculas
    - solo [a-z0-9._-]
    - máximo 32 chars
    """
    if not usuario:
        raise ValueError("usuario vacío")
    u = str(usuario).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9._-]{0,31}", u):
        raise ValueError(f"nombre de usuario no válido para NAS: {usuario!r}")
    return u


def home_de(usuario):
    """Path absoluto del home del usuario. Normaliza a minúsculas."""
    return NAS_BASE / _normalizar_usuario(usuario)


def resolver(usuario, rel, debe_existir=True):
    """Resuelve una ruta relativa dentro del home del usuario.
    Devuelve un Path o lanza ValueError."""
    rel_ok = _limpiar_rel(rel)
    home = home_de(usuario).resolve()
    objetivo = (home / rel_ok).resolve() if rel_ok else home
    try:
        objetivo.relative_to(home)
    except ValueError:
        raise ValueError("ruta fuera del home")
    if debe_existir and not objetivo.exists():
        raise ValueError("no existe")
    return objetivo


def asegurar_home(usuario):
    """Crea la base del NAS y el home del usuario si no existen.
    Lanza ValueError con mensaje claro si no se puede."""
    # 1) Crear NAS_BASE si no existe
    if not NAS_BASE.exists():
        try:
            NAS_BASE.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise ValueError(
                f"No se puede crear {NAS_BASE}. "
                f"Configura otra ruta en NAS_BASE o pide permisos al admin."
            )
        except Exception as e:
            raise ValueError(f"No se pudo crear {NAS_BASE}: {e}")

    if not os.access(str(NAS_BASE), os.W_OK):
        raise ValueError(
            f"Sin permisos de escritura sobre {NAS_BASE}. "
            f"Pide al admin: chown {os.getenv('USER','?')} {NAS_BASE}"
        )

    # 2) Crear home del usuario
    home = home_de(usuario)
    if home.exists():
        if not os.access(str(home), os.R_OK):
            raise ValueError(f"Sin permisos de lectura sobre {home}")
        return home
    try:
        home.mkdir(parents=True, exist_ok=True)
        return home
    except PermissionError:
        raise ValueError(
            f"No se puede crear {home}: sin permisos en {NAS_BASE}."
        )
    except Exception as e:
        raise ValueError(f"No se pudo preparar el home: {e}")


# ─── Listado ─────────────────────────────────────────────────
def listar(usuario, rel=""):
    home = home_de(usuario).resolve()
    objetivo = resolver(usuario, rel, debe_existir=True)
    if not objetivo.is_dir():
        raise ValueError("no es un directorio")

    items = []
    try:
        for entry in os.scandir(objetivo):
            try:
                st = entry.stat(follow_symlinks=False)
                es_dir = entry.is_dir(follow_symlinks=False)
                es_link = entry.is_symlink()
                # Si es symlink a un dir, marcarlo como dir también
                if es_link and not es_dir:
                    try:
                        es_dir = Path(entry.path).is_dir()
                    except Exception:
                        pass

                ext = ""
                if not es_dir:
                    n = entry.name
                    if "." in n:
                        ext = n.rsplit(".", 1)[1].lower()[:12]

                # Ruta relativa para el frontend
                try:
                    rel_item = str(Path(entry.path).relative_to(home))
                except Exception:
                    rel_item = entry.name

                items.append({
                    "nombre":   entry.name,
                    "rel":      rel_item,
                    "es_dir":   bool(es_dir),
                    "es_link":  bool(es_link),
                    "size":     int(st.st_size) if not es_dir else 0,
                    "mtime":    datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                    "ext":      ext,
                })
            except Exception:
                continue
    except PermissionError:
        raise ValueError("sin permisos para listar este directorio")

    # Ordenar: directorios primero, luego por nombre (case-insensitive)
    items.sort(key=lambda x: (not x["es_dir"], x["nombre"].lower()))

    # Ruta relativa actual (para breadcrumb) y padre
    rel_actual = ""
    try:
        rel_actual = str(objetivo.relative_to(home))
        if rel_actual == ".":
            rel_actual = ""
    except Exception:
        pass

    padre = None
    if rel_actual:
        padre = "/".join(rel_actual.split("/")[:-1])

    return {
        "path":    rel_actual,
        "padre":   padre,
        "home":    str(home),
        "items":   items,
    }


# ─── Operaciones ─────────────────────────────────────────────
def mkdir(usuario, rel, nombre):
    nombre = _limpiar_nombre(nombre)
    carpeta = resolver(usuario, rel, debe_existir=True)
    if not carpeta.is_dir():
        raise ValueError("la ruta base no es un directorio")
    nueva = carpeta / nombre
    if nueva.exists():
        raise ValueError(f"ya existe '{nombre}'")
    nueva.mkdir()
    return str(nueva.relative_to(home_de(usuario).resolve()))


def renombrar(usuario, rel, nuevo_nombre):
    nuevo_nombre = _limpiar_nombre(nuevo_nombre)
    objetivo = resolver(usuario, rel, debe_existir=True)
    home = home_de(usuario).resolve()
    if objetivo == home:
        raise ValueError("no se puede renombrar el home")
    destino = objetivo.parent / nuevo_nombre
    if destino.exists():
        raise ValueError(f"ya existe '{nuevo_nombre}'")
    objetivo.rename(destino)
    return str(destino.relative_to(home))


def eliminar(usuario, rel):
    objetivo = resolver(usuario, rel, debe_existir=True)
    home = home_de(usuario).resolve()
    if objetivo == home:
        raise ValueError("no se puede eliminar el home")
    if objetivo.is_dir():
        shutil.rmtree(objetivo)
    else:
        objetivo.unlink()


def guardar_upload(usuario, rel, file_storage, nombre_forzado=None):
    """Guarda un archivo subido. Devuelve dict con info del archivo guardado."""
    destino_dir = resolver(usuario, rel, debe_existir=True)
    if not destino_dir.is_dir():
        raise ValueError("el destino no es un directorio")

    nombre = nombre_forzado or file_storage.filename or "sin_nombre"
    # Quedarse solo con el basename del path del cliente
    nombre = os.path.basename(nombre.replace(chr(92), "/"))
    nombre = _limpiar_nombre(nombre)

    destino = destino_dir / nombre
    # Si existe, añadir sufijo _1, _2, ...
    base, ext = os.path.splitext(nombre)
    i = 1
    while destino.exists():
        destino = destino_dir / f"{base}_{i}{ext}"
        i += 1

    file_storage.save(str(destino))
    st = destino.stat()
    home = home_de(usuario).resolve()
    return {
        "nombre":  destino.name,
        "rel":     str(destino.relative_to(home)),
        "size":    int(st.st_size),
        "mtime":   datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


def info(usuario, rel):
    objetivo = resolver(usuario, rel, debe_existir=True)
    st = objetivo.stat()
    home = home_de(usuario).resolve()
    try:
        rel_str = str(objetivo.relative_to(home))
    except Exception:
        rel_str = objetivo.name
    return {
        "nombre": objetivo.name,
        "rel":    rel_str,
        "abs":    str(objetivo),
        "es_dir": objetivo.is_dir(),
        "size":   int(st.st_size) if not objetivo.is_dir() else 0,
        "mtime":  datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


def mimetype_de(nombre):
    mt, _ = mimetypes.guess_type(nombre)
    return mt or "application/octet-stream"


def uso_disco(usuario):
    """Tamaño total ocupado en el home del usuario (bytes)."""
    home = home_de(usuario).resolve()
    if not home.exists():
        return 0
    total = 0
    for root, _, files in os.walk(home):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total


def validar_url_wget(url):
    """Solo http/https. No permite file:// ni similares."""
    if not url:
        raise ValueError("URL vacía")
    u = url.strip()
    if len(u) > 2000:
        raise ValueError("URL demasiado larga")
    if not (u.startswith("http://") or u.startswith("https://")):
        raise ValueError("solo se permite http:// o https://")
    return u

# ─── ZIP de carpeta ──────────────────────────────────────────
ZIP_MAX_BYTES = 2 * 1024 * 1024 * 1024   # 2 GB máx para generar ZIP


def crear_zip_de(usuario, rel):
    """Comprime la carpeta `rel` (o el home si vacío). Devuelve (path_temp, nombre_sugerido).
    El caller debe borrar el archivo temporal después."""
    objetivo = resolver(usuario, rel, debe_existir=True)
    if not objetivo.is_dir():
        raise ValueError("No es un directorio")
    home = home_de(usuario).resolve()

    # Calcular tamaño total para evitar llenar el disco
    total = 0
    for root, _, files in os.walk(objetivo):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                if total > ZIP_MAX_BYTES:
                    raise ValueError(
                        f"La carpeta supera {ZIP_MAX_BYTES // (1024**3)} GB. "
                        "Descarga por partes o usa rsync/scp."
                    )
            except OSError:
                pass

    nombre_base = objetivo.name if objetivo != home else "home_" + usuario
    nombre_zip  = f"{nombre_base}.zip"

    tmp = tempfile.NamedTemporaryFile(
        prefix="naszip_", suffix=".zip", delete=False,
        dir=str(Path(Config.DATA_DIR)) if Path(Config.DATA_DIR).exists() else None,
    )
    tmp.close()

    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for root, dirs, files in os.walk(objetivo):
                for f in files:
                    abs_f = os.path.join(root, f)
                    try:
                        rel_arc = os.path.relpath(abs_f, objetivo)
                        # Seguridad: no permitir symlinks que escapen
                        real = os.path.realpath(abs_f)
                        if not real.startswith(str(objetivo)):
                            continue
                        zf.write(abs_f, arcname=rel_arc)
                    except (OSError, ValueError):
                        continue
    except Exception:
        try: os.unlink(tmp.name)
        except Exception: pass
        raise

    return tmp.name, nombre_zip


# ═══════════════════════════════════════════════════════════════
# PREVIEW
# ═══════════════════════════════════════════════════════════════
_MAX_PREVIEW_BYTES = 500 * 1024   # 500 KB para text/notebook/csv

_EXT_IMAGE = {"png","jpg","jpeg","gif","webp","svg","bmp","ico","tiff"}
_EXT_PDF   = {"pdf"}
_EXT_TEXT  = {"txt","md","rst","log","py","js","ts","tsx","jsx","sh","bash",
              "yml","yaml","json","xml","html","htm","css","scss",
              "c","cpp","cc","h","hpp","java","go","rs","rb","php",
              "sql","ini","cfg","conf","toml","env"}
_EXT_CSV   = {"csv","tsv"}
_EXT_NOTE  = {"ipynb"}


def _tipo_preview(nombre):
    if "." not in nombre:
        return "binary"
    ext = nombre.rsplit(".", 1)[1].lower()
    if ext in _EXT_IMAGE:  return "image"
    if ext in _EXT_PDF:    return "pdf"
    if ext in _EXT_NOTE:   return "notebook"
    if ext in _EXT_CSV:    return "csv"
    if ext in _EXT_TEXT:   return "text"
    return "binary"


def _notebook_limpio(nb):
    celdas = []
    for c in nb.get("cells", [])[:200]:
        tipo = c.get("cell_type", "code")
        src_c = c.get("source", "")
        if isinstance(src_c, list):
            src_c = "".join(src_c)
        item = {"tipo": tipo, "fuente": src_c}
        if tipo == "code":
            outs = []
            for o in c.get("outputs", [])[:20]:
                ot = o.get("output_type")
                if ot == "stream":
                    txt = o.get("text", "")
                    if isinstance(txt, list): txt = "".join(txt)
                    outs.append({"tipo": "texto", "data": txt})
                elif ot in ("execute_result", "display_data"):
                    data = o.get("data", {})
                    if "text/plain" in data:
                        t = data["text/plain"]
                        if isinstance(t, list): t = "".join(t)
                        outs.append({"tipo": "texto", "data": t})
                    elif "text/html" in data:
                        h = data["text/html"]
                        if isinstance(h, list): h = "".join(h)
                        outs.append({"tipo": "html", "data": h})
                elif ot == "error":
                    outs.append({"tipo": "error",
                                 "data": "\n".join(o.get("traceback", []))})
            item["outputs"] = outs
        celdas.append(item)
    meta = nb.get("metadata", {})
    return {
        "kernel":   meta.get("kernelspec", {}).get("display_name", "?"),
        "language": meta.get("language_info", {}).get("name", "?"),
        "celdas":   celdas,
    }


def preview(usuario, rel):
    objetivo = resolver(usuario, rel, debe_existir=True)
    if objetivo.is_dir():
        raise ValueError("Es un directorio")
    nombre = objetivo.name
    tipo = _tipo_preview(nombre)
    st = objetivo.stat()
    base = {
        "nombre": nombre,
        "rel":    rel,
        "abs":    str(objetivo),
        "tipo":   tipo,
        "size":   int(st.st_size),
        "mtime":  datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }

    if tipo in ("image", "pdf", "binary"):
        return base

    try:
        with open(objetivo, "rb") as f:
            raw = f.read(_MAX_PREVIEW_BYTES)
    except Exception as e:
        raise ValueError(f"No se pudo leer: {e}")

    base["truncado"] = st.st_size > _MAX_PREVIEW_BYTES

    try:
        texto = raw.decode("utf-8", errors="replace")
    except Exception:
        texto = raw.decode("latin-1", errors="replace")

    if tipo == "text":
        base["texto"] = texto
        return base

    if tipo == "notebook":
        try:
            nb = json.loads(texto)
            base["notebook"] = _notebook_limpio(nb)
        except Exception as e:
            base["texto"] = texto
            base["tipo"] = "text"
            base["nota"] = f"No se pudo parsear como notebook: {e}"
        return base

    if tipo == "csv":
        try:
            delim = "\t" if nombre.lower().endswith(".tsv") else ","
            reader = csv.reader(io.StringIO(texto), delimiter=delim)
            filas = []
            for i, row in enumerate(reader):
                filas.append(row)
                if i >= 100:
                    break
            base["filas"] = filas
            base["delim"] = "tab" if delim == "\t" else "coma"
        except Exception as e:
            base["texto"] = texto
            base["tipo"] = "text"
            base["nota"] = f"No se pudo parsear como CSV: {e}"
        return base

    return base


# ═══════════════════════════════════════════════════════════════
# BULK — mover, eliminar múltiple, zip múltiple
# ═══════════════════════════════════════════════════════════════
def mover(usuario, rels, destino_rel):
    destino = resolver(usuario, destino_rel, debe_existir=True)
    if not destino.is_dir():
        raise ValueError("El destino no es un directorio")
    home = home_de(usuario).resolve()

    movidos, errores = [], []
    for rel in rels:
        try:
            origen = resolver(usuario, rel, debe_existir=True)
            if origen == home:
                errores.append({"rel": rel, "error": "no se puede mover el home"})
                continue
            # Evitar mover carpeta dentro de sí misma
            try:
                destino.relative_to(origen)
                errores.append({"rel": rel, "error": "destino dentro del origen"})
                continue
            except ValueError:
                pass
            nuevo = destino / origen.name
            if nuevo.exists():
                base, ext = os.path.splitext(origen.name)
                i = 1
                while nuevo.exists():
                    nuevo = destino / f"{base}_{i}{ext}"
                    i += 1
            shutil.move(str(origen), str(nuevo))
            movidos.append(str(nuevo.relative_to(home)))
        except Exception as e:
            errores.append({"rel": rel, "error": str(e)})
    return {"movidos": movidos, "errores": errores}


def eliminar_muchos(usuario, rels):
    home = home_de(usuario).resolve()
    eliminados, errores = [], []
    for rel in rels:
        try:
            objetivo = resolver(usuario, rel, debe_existir=True)
            if objetivo == home:
                errores.append({"rel": rel, "error": "no se puede eliminar el home"})
                continue
            if objetivo.is_dir():
                shutil.rmtree(objetivo)
            else:
                objetivo.unlink()
            eliminados.append(rel)
        except Exception as e:
            errores.append({"rel": rel, "error": str(e)})
    return {"eliminados": eliminados, "errores": errores}


def crear_zip_multiple(usuario, rels):
    """ZIP con múltiples archivos/carpetas."""
    if not rels:
        raise ValueError("Sin rutas")
    home = home_de(usuario).resolve()
    total = 0
    archivos = []
    for rel in rels:
        objetivo = resolver(usuario, rel, debe_existir=True)
        if objetivo == home:
            raise ValueError("no se puede comprimir el home entero aquí")
        if objetivo.is_file():
            try:
                total += objetivo.stat().st_size
                if total > ZIP_MAX_BYTES:
                    raise ValueError("Excede tamaño máximo")
            except OSError:
                pass
            archivos.append((objetivo, objetivo.name))
        else:
            for root, _, files in os.walk(objetivo):
                for f in files:
                    abs_f = os.path.join(root, f)
                    try:
                        total += os.path.getsize(abs_f)
                        if total > ZIP_MAX_BYTES:
                            raise ValueError("Excede tamaño máximo")
                    except OSError:
                        pass
                    rel_arc = os.path.join(objetivo.name, os.path.relpath(abs_f, objetivo))
                    archivos.append((Path(abs_f), rel_arc))

    nombre_zip = f"seleccion_{len(rels)}_items.zip"
    tmp = tempfile.NamedTemporaryFile(prefix="naszip_", suffix=".zip", delete=False)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for abs_f, arcname in archivos:
                try:
                    real = os.path.realpath(str(abs_f))
                    if not real.startswith(str(home)):
                        continue
                    zf.write(str(abs_f), arcname=arcname)
                except (OSError, ValueError):
                    continue
    except Exception:
        try: os.unlink(tmp.name)
        except Exception: pass
        raise
    return tmp.name, nombre_zip
