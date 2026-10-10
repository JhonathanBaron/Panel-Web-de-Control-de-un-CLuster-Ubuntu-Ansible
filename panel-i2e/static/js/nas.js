// ═══════════════════════════════════════════════════════════════
// NAS Browser — navegar, subir, bajar, wget, copiar rutas
// ═══════════════════════════════════════════════════════════════

let _nasPath   = "";          // ruta relativa actual
let _nasHome   = "";          // ruta absoluta del home
let _nasItems  = [];          // items del directorio actual
let _nasPadre  = null;
let _nasSort   = { field: "nombre", dir: 1 };   // nombre | size | mtime
let _nasBuscar = "";

// ─── Formato ─────────────────────────────────────────────────
function _fmtSize(b) {
    if (b === 0 || b === null || b === undefined) return "—";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0, x = Number(b);
    while (x >= 1024 && i < u.length - 1) { x /= 1024; i++; }
    return (i === 0 ? x : x.toFixed(x < 10 ? 1 : 0)) + " " + u[i];
}

function _fmtFecha(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getDate())}/${p(d.getMonth()+1)}/${String(d.getFullYear()).slice(2)} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function _iconoArchivo(item) {
    if (item.es_dir) return "folder";
    const e = (item.ext || "").toLowerCase();
    if (["py","ipynb","js","ts","sh","yml","yaml","json","xml","html","css","c","cpp","h","java","go","rs"].includes(e)) return "file-code";
    if (["png","jpg","jpeg","gif","webp","svg","bmp","tiff"].includes(e)) return "file-image";
    if (["zip","tar","gz","bz2","xz","7z","rar"].includes(e)) return "file-zip";
    if (["pt","pth","h5","onnx","pb","safetensors","ckpt","bin","npz","npy","csv","parquet"].includes(e)) return "file-data";
    if (["txt","md","log","rst"].includes(e)) return "file-text";
    return "file";
}

// ─── Cargar ──────────────────────────────────────────────────
async function cargarNas(ruta) {
    if (typeof ruta === "string") _nasPath = ruta;
    const cont = document.getElementById("nas-lista");
    if (!cont) return;
    cont.innerHTML = '<div class="empty"><span class="spin"></span> Cargando…</div>';

    try {
        const data = await api(`/api/nas/list?path=${encodeURIComponent(_nasPath || "")}`);
        if (data.status !== "success") {
            cont.innerHTML = `<div class="empty">Error: ${escapeHtml(data.output || "")}</div>`;
            return;
        }
        _nasHome  = data.home || "";
        _nasItems = data.items || [];
        _nasPadre = data.padre;
        _nasPath  = data.path || "";

        _renderBreadcrumb();
        _renderUso(data.uso_bytes);
        _renderLista();
    } catch (e) {
        cont.innerHTML = `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
    }
}

// ─── Breadcrumb ──────────────────────────────────────────────
function _renderBreadcrumb() {
    const bc = document.getElementById("nas-breadcrumb");
    if (!bc) return;
    const partes = _nasPath ? _nasPath.split("/") : [];

    let html = `<a href="#" class="nas-crumb" data-rel="">🏠 home</a>`;
    let acum = "";
    for (const p of partes) {
        acum = acum ? acum + "/" + p : p;
        html += `<span class="nas-crumb-sep">/</span>` +
                `<a href="#" class="nas-crumb" data-rel="${escapeHtml(acum)}">${escapeHtml(p)}</a>`;
    }
    bc.innerHTML = html;

    bc.querySelectorAll(".nas-crumb").forEach(a => {
        a.addEventListener("click", e => {
            e.preventDefault();
            cargarNas(a.dataset.rel);
        });
    });
}

function _renderUso(bytes) {
    const el = document.getElementById("nas-uso");
    if (el) el.textContent = `Uso: ${_fmtSize(bytes)}`;
    const home = document.getElementById("nas-home");
    if (home) home.textContent = _nasHome;
}

// ─── Lista ───────────────────────────────────────────────────
function _renderLista() {
    const cont = document.getElementById("nas-lista");
    if (!cont) return;

    let items = [..._nasItems];

    // Filtro
    if (_nasBuscar) {
        const q = _nasBuscar.toLowerCase();
        items = items.filter(i => i.nombre.toLowerCase().includes(q));
    }

    // Ordenar
    const { field, dir } = _nasSort;
    items.sort((a, b) => {
        if (a.es_dir !== b.es_dir) return a.es_dir ? -1 : 1;
        let va = a[field], vb = b[field];
        if (field === "nombre") { va = va.toLowerCase(); vb = vb.toLowerCase(); }
        if (va < vb) return -1 * dir;
        if (va > vb) return 1 * dir;
        return 0;
    });

    if (items.length === 0) {
        cont.innerHTML = `<div class="empty">Carpeta vacía${_nasBuscar ? " (sin coincidencias)" : ""}</div>`;
        return;
    }

    const fila = i => `
        <div class="nas-item${i.es_dir ? " nas-dir" : ""}" data-rel="${escapeHtml(i.rel)}" data-dir="${i.es_dir ? '1' : '0'}">
            <span class="nas-ic" data-ico="${_iconoArchivo(i)}"></span>
            <span class="nas-nombre" title="${escapeHtml(i.nombre)}">${escapeHtml(i.nombre)}${i.es_link ? ' <span class="nas-link">→</span>' : ''}</span>
            <span class="nas-tam">${i.es_dir ? "—" : _fmtSize(i.size)}</span>
            <span class="nas-fecha">${_fmtFecha(i.mtime)}</span>
            <span class="nas-acts">
                <button class="nas-btn nas-btn-dl" title="${i.es_dir ? 'Descargar carpeta (ZIP)' : 'Descargar'}" data-act="download"><span data-ico="download"></span></button>
                <button class="nas-btn" title="Copiar ruta…" data-act="copy"><span data-ico="copy"></span></button>
                <button class="nas-btn" title="Renombrar" data-act="rename"><span data-ico="pencil"></span></button>
                <button class="nas-btn nas-btn-r" title="Eliminar" data-act="delete"><span data-ico="trash"></span></button>
            </span>
        </div>`;

    let html = "";
    if (_nasPadre !== null) {
        html += `<div class="nas-item nas-up" data-rel="${escapeHtml(_nasPadre)}" data-dir="1">
            <span class="nas-ic" data-ico="folder-up"></span>
            <span class="nas-nombre">.. (subir)</span>
            <span class="nas-tam"></span><span class="nas-fecha"></span><span class="nas-acts"></span>
        </div>`;
    }
    html += items.map(fila).join("");
    cont.innerHTML = html;

    // Eventos
    cont.querySelectorAll(".nas-item").forEach(row => {
        const rel = row.dataset.rel;
        const esDir = row.dataset.dir === "1";

        row.querySelector(".nas-nombre")?.addEventListener("click", () => {
            if (esDir) cargarNas(rel);
        });
        if (esDir) row.querySelector(".nas-ic")?.addEventListener("click", () => cargarNas(rel));

        row.querySelectorAll(".nas-btn").forEach(btn => {
            btn.addEventListener("click", e => {
                e.stopPropagation();
                const act = btn.dataset.act;
                const item = _nasItems.find(x => x.rel === rel) || { rel, nombre: rel.split("/").pop(), es_dir: esDir };
                if (act === "download") {
                    if (esDir) _nasDescargarZip(item);
                    else       _nasDescargar(item);
                }
                if (act === "copy")     _nasCopiarMenu(item, btn);
                if (act === "rename")   _nasRenombrar(item);
                if (act === "delete")   _nasEliminar(item);
            });
        });

        // Doble clic en fila → navegar o descargar
        row.addEventListener("dblclick", (e) => {
            if (esDir) {
                if (e.altKey) _nasDescargarZip({ rel, nombre: rel.split("/").pop() });
                else cargarNas(rel);
            } else {
                _nasDescargar({ rel, nombre: rel.split("/").pop() });
            }
        });
    });
}

// ─── Acciones ────────────────────────────────────────────────
function _nasDescargar(item) {
    const url = `/api/nas/download?path=${encodeURIComponent(item.rel)}`;
    const a = document.createElement("a");
    a.href = url;
    a.download = item.nombre;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 100);
    toast(`Descargando ${item.nombre}…`, "info");
}

// ─── Descargar carpeta como ZIP ──────────────────────────────
function _nasDescargarZip(item) {
    const url = `/api/nas/download-zip?path=${encodeURIComponent(item.rel || "")}`;
    toast(`Empaquetando "${item.nombre}"…`, "info");
    // Navegar directamente: el navegador gestiona la descarga
    const a = document.createElement("a");
    a.href = url;
    a.download = (item.nombre || "home") + ".zip";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 100);
}

// ─── Descargar carpeta ACTUAL como ZIP ───────────────────────
function nasDescargarActualZip() {
    const nombre = _nasPath ? _nasPath.split("/").pop() : "home";
    _nasDescargarZip({ rel: _nasPath || "", nombre });
}


function _nasCopiarMenu(item, btn) {
    const rel   = item.rel;
    const abs   = _nasHome + "/" + rel;
    const lineas = [
        { label: "Ruta absoluta",    val: abs,          icon: "copy" },
        { label: "Ruta relativa",    val: rel,          icon: "copy" },
        { label: "Como string Python", val: `"${abs}"`, icon: "file-code" },
        { label: "Como variable shell", val: `NAS=${abs}`, icon: "terminal" },
    ];

    document.getElementById("nas-copymenu")?.remove();
    const r = btn.getBoundingClientRect();
    const html = `
        <div id="nas-copymenu" class="nas-copymenu" style="top:${r.bottom + 4}px; left:${Math.max(8, r.right - 220)}px;">
            ${lineas.map(l => `<div class="nas-copymenu-item" data-val="${escapeHtml(l.val)}">
                <span data-ico="${l.icon}"></span>${escapeHtml(l.label)}
            </div>`).join("")}
        </div>`;
    document.body.insertAdjacentHTML("beforeend", html);

    const menu = document.getElementById("nas-copymenu");
    menu.querySelectorAll(".nas-copymenu-item").forEach(el => {
        el.addEventListener("click", async () => {
            const ok = await copiarAlPortapapeles(el.dataset.val);
            toast(ok ? "Copiado" : "No se pudo copiar", ok ? "success" : "error");
            menu.remove();
        });
    });
    setTimeout(() => document.addEventListener("click", function cerrar(e) {
        if (!e.target.closest("#nas-copymenu")) { menu.remove(); document.removeEventListener("click", cerrar); }
    }), 10);
}

async function _nasRenombrar(item) {
    const nuevo = prompt(`Nuevo nombre para "${item.nombre}":`, item.nombre);
    if (!nuevo || nuevo === item.nombre) return;
    try {
        const data = await api("/api/nas/rename", {
            method: "POST",
            body: JSON.stringify({ path: item.rel, nuevo })
        });
        if (data.status !== "success") { toast("Error: " + data.output, "error"); return; }
        toast("Renombrado", "success");
        cargarNas();
    } catch (e) { toast("Error: " + e.message, "error"); }
}

async function _nasEliminar(item) {
    const tipo = item.es_dir ? "la carpeta (y su contenido)" : "el archivo";
    if (!confirm(`¿Eliminar ${tipo} "${item.nombre}"?\n\nNo se puede deshacer.`)) return;
    try {
        const data = await api("/api/nas/delete", {
            method: "POST",
            body: JSON.stringify({ path: item.rel })
        });
        if (data.status !== "success") { toast("Error: " + data.output, "error"); return; }
        toast("Eliminado", "success");
        cargarNas();
    } catch (e) { toast("Error: " + e.message, "error"); }
}

// ─── Nueva carpeta ───────────────────────────────────────────
async function nasNuevaCarpeta() {
    const nombre = prompt("Nombre de la nueva carpeta:");
    if (!nombre) return;
    try {
        const data = await api("/api/nas/mkdir", {
            method: "POST",
            body: JSON.stringify({ path: _nasPath, nombre })
        });
        if (data.status !== "success") { toast("Error: " + data.output, "error"); return; }
        toast("Carpeta creada", "success");
        cargarNas();
    } catch (e) { toast("Error: " + e.message, "error"); }
}

// ─── wget ────────────────────────────────────────────────────
async function nasWget() {
    const url = prompt("URL a descargar (http:// o https://):");
    if (!url) return;
    try {
        const data = await api("/api/nas/wget", {
            method: "POST",
            body: JSON.stringify({ url: url.trim(), path: _nasPath })
        });
        if (data.status !== "success") { toast("Error: " + data.output, "error"); return; }
        toast("Descarga lanzada en background. Verás el progreso en Playbooks > Historial.", "success", 6000);
    } catch (e) { toast("Error: " + e.message, "error"); }
}

// ─── Upload ──────────────────────────────────────────────────
function nasSubirClick() {
    const input = document.getElementById("nas-file-input");
    if (input) { input.value = ""; input.click(); }
}

async function _nasSubirArchivos(files) {
    if (!files || !files.length) return;
    const barra = document.getElementById("nas-upload-bar");
    const barraIn = document.getElementById("nas-upload-fill");
    const barraTx = document.getElementById("nas-upload-txt");
    if (barra) barra.classList.remove("oculto");

    let ok = 0, fail = 0;
    for (let i = 0; i < files.length; i++) {
        const f = files[i];
        if (barraTx) barraTx.textContent = `Subiendo ${i+1}/${files.length}: ${f.name}`;
        if (barraIn) barraIn.style.width = "0%";

        try {
            await _uploadUno(f, pct => {
                if (barraIn) barraIn.style.width = pct + "%";
            });
            ok++;
        } catch (e) {
            console.error("upload", f.name, e);
            fail++;
            toast(`Error subiendo ${f.name}: ${e.message}`, "error", 5000);
        }
    }

    if (barraTx) barraTx.textContent = `✓ ${ok} subido(s)${fail ? " · " + fail + " fallo(s)" : ""}`;
    if (barraIn) barraIn.style.width = "100%";
    setTimeout(() => barra?.classList.add("oculto"), 2000);
    cargarNas();
}

function _uploadUno(file, onProgress) {
    return new Promise((resolve, reject) => {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("path", _nasPath);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/nas/upload");
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
        if (csrf) xhr.setRequestHeader("X-CSRFToken", csrf);

        xhr.upload.addEventListener("progress", e => {
            if (e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
        });
        xhr.addEventListener("load", () => {
            if (xhr.status >= 200 && xhr.status < 300) {
                try { resolve(JSON.parse(xhr.responseText)); }
                catch { reject(new Error("respuesta inválida")); }
            } else {
                let msg = `HTTP ${xhr.status}`;
                try { msg = JSON.parse(xhr.responseText).output || msg; } catch {}
                reject(new Error(msg));
            }
        });
        xhr.addEventListener("error", () => reject(new Error("error de red")));
        xhr.send(fd);
    });
}

// ─── Drag & drop ─────────────────────────────────────────────
function _setupDropzone() {
    const zona = document.getElementById("tab-nas");
    if (!zona) return;
    let pendientes = 0;

    zona.addEventListener("dragenter", e => {
        e.preventDefault(); e.stopPropagation();
        pendientes++;
        zona.classList.add("nas-dragging");
    });
    zona.addEventListener("dragover", e => e.preventDefault());
    zona.addEventListener("dragleave", e => {
        e.preventDefault(); e.stopPropagation();
        pendientes--;
        if (pendientes <= 0) { pendientes = 0; zona.classList.remove("nas-dragging"); }
    });
    zona.addEventListener("drop", e => {
        e.preventDefault(); e.stopPropagation();
        pendientes = 0; zona.classList.remove("nas-dragging");
        const files = Array.from(e.dataTransfer?.files || []);
        if (files.length) _nasSubirArchivos(files);
    });
}

// ─── Orden ───────────────────────────────────────────────────
function nasOrdenar(field) {
    if (_nasSort.field === field) _nasSort.dir *= -1;
    else _nasSort = { field, dir: 1 };
    _renderLista();
}

// ─── Arranque ────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    const tab = document.querySelector('.tab[data-tab="nas"]');
    if (tab) tab.addEventListener("click", () => {
        if (!document.getElementById("nas-lista")?.children.length ||
            document.getElementById("nas-lista")?.querySelector(".empty")) {
            cargarNas("");
        }
    });

    const btnSubir = document.getElementById("nas-btn-subir");
    if (btnSubir) btnSubir.addEventListener("click", nasSubirClick);

    const input = document.getElementById("nas-file-input");
    if (input) input.addEventListener("change", e => _nasSubirArchivos(Array.from(e.target.files || [])));

    const buscar = document.getElementById("nas-buscar");
    if (buscar) buscar.addEventListener("input", e => { _nasBuscar = e.target.value; _renderLista(); });

    _setupDropzone();
});

// Exponer
window.cargarNas       = cargarNas;
window.nasNuevaCarpeta = nasNuevaCarpeta;
window.nasWget         = nasWget;
window.nasSubirClick   = nasSubirClick;
window.nasOrdenar      = nasOrdenar;
window.nasDescargarActualZip = nasDescargarActualZip;


// ═══════════════════════════════════════════════════════════════
// NAS multi-usuario (solo admin/operator)
// ═══════════════════════════════════════════════════════════════
let nasUsuarioActual = null;   // null = el propio usuario

async function cargarSelectorUsuariosNas() {
    const sel = document.getElementById('nas-usuario-select');
    if (!sel) return;

    // SOLO admin ve el selector de usuarios
    const role = document.querySelector('.hdr-badge')?.textContent?.trim();
    if (role !== 'admin') {
        sel.style.display = 'none';
        return;
    }

    try {
        const data = await api('/api/nas/usuarios');
        if (data.status !== 'success') return;

        const usuarios = data.usuarios || [];
        const yo = document.querySelector('.hdr-user')?.textContent?.trim() || '';

        sel.innerHTML = '<option value="">👤 Mi NAS (' + escapeHtml(yo) + ')</option>' +
            usuarios.map(u =>
                `<option value="${escapeHtml(u.username)}">${escapeHtml(u.username)}</option>`
            ).join('');

        sel.addEventListener('change', () => {
            nasUsuarioActual = sel.value || null;
            cargarNas('');   // recargar raíz del usuario seleccionado
        });
    } catch (e) {
        console.warn('[nas-usuarios]', e);
    }
}

// Envuelve api() para añadir ?user= en peticiones NAS
(function() {
    const _apiOrig = window.api;
    if (!_apiOrig || _apiOrig.__nasWrapped) return;

    window.api = async function(url, opts) {
        if (nasUsuarioActual && url.startsWith('/api/nas/')) {
            const sep = url.includes('?') ? '&' : '?';
            url = url + sep + 'user=' + encodeURIComponent(nasUsuarioActual);
        }
        return _apiOrig(url, opts);
    };
    window.api.__nasWrapped = true;
})();

document.addEventListener('DOMContentLoaded', () => {
    setTimeout(cargarSelectorUsuariosNas, 800);
});
