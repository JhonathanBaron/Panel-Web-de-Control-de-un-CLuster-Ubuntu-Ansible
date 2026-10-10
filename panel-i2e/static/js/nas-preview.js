// ═══════════════════════════════════════════════════════════════
// Vista previa de archivos del NAS
// ═══════════════════════════════════════════════════════════════

// ─── Markdown mínimo (sin deps) ──────────────────────────────
function _mdMin(txt) {
    let h = escapeHtml(txt);
    // Code fences
    h = h.replace(/```([\s\S]*?)```/g, (_, c) => `<pre class="md-code">${c.replace(/^\w+\n/, "")}</pre>`);
    // Headers
    h = h.replace(/^###### (.*)$/gm, '<h6>$1</h6>')
         .replace(/^##### (.*)$/gm,  '<h5>$1</h5>')
         .replace(/^#### (.*)$/gm,   '<h4>$1</h4>')
         .replace(/^### (.*)$/gm,    '<h3>$1</h3>')
         .replace(/^## (.*)$/gm,     '<h2>$1</h2>')
         .replace(/^# (.*)$/gm,      '<h1>$1</h1>');
    // Bold / italic / code
    h = h.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
         .replace(/\*(.+?)\*/g,     '<i>$1</i>')
         .replace(/`([^`]+)`/g,     '<code>$1</code>');
    // Links
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // Listas
    h = h.replace(/^[ \t]*[-*] (.*)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>[\s\S]*?<\/li>)/g, m => `<ul>${m}</ul>`);
    // Párrafos (doble salto)
    h = h.split(/\n{2,}/).map(p =>
        /^<(h\d|ul|pre|blockquote)/.test(p.trim()) ? p : `<p>${p.replace(/\n/g, '<br>')}</p>`
    ).join('');
    return h;
}

// ─── Modal principal ─────────────────────────────────────────
async function abrirPreview(item) {
    document.getElementById('modal-nas-preview')?.remove();

    const html = `
        <div class="modal-bg show" id="modal-nas-preview"
             onclick="if(event.target===this)cerrarPreview()">
            <div class="modal modal-preview">
                <div class="preview-head">
                    <div class="preview-title">
                        <span data-ico="file"></span>
                        <b id="pv-nombre">${escapeHtml(item.nombre)}</b>
                        <span class="preview-size" id="pv-meta"></span>
                    </div>
                    <button class="hdr-btn" onclick="cerrarPreview()" title="Cerrar">
                        <span data-ico="x"></span>
                    </button>
                </div>
                <div class="preview-body" id="pv-body">
                    <div class="empty"><span class="spin"></span> Cargando vista previa…</div>
                </div>
                <div class="preview-foot">
                    <button class="btn btn-b" onclick="pvCopiarRuta('${escapeHtml(item.rel)}')">
                        <span data-ico="copy"></span>Copiar ruta
                    </button>
                    <button class="btn btn-b" onclick="pvCopiarPython('${escapeHtml(item.rel)}')">
                        <span data-ico="file-code"></span>Python
                    </button>
                    <button class="btn btn-n" onclick="pvDescargar('${escapeHtml(item.rel)}','${escapeHtml(item.nombre)}')">
                        <span data-ico="download"></span>Descargar
                    </button>
                    <div style="flex:1;"></div>
                    <button class="btn btn-n" onclick="cerrarPreview()">Cerrar</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);

    try {
        const data = await api(`/api/nas/preview?path=${encodeURIComponent(item.rel)}`);
        if (data.status !== 'success') throw new Error(data.output || 'error');
        const pv = data.preview;
        document.getElementById('pv-meta').textContent =
            `${_fmtSize(pv.size)} · ${pv.tipo} · ${pv.mtime}`;
        _renderPreview(pv);
    } catch (e) {
        document.getElementById('pv-body').innerHTML =
            `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function cerrarPreview() {
    document.getElementById('modal-nas-preview')?.remove();
}

// ─── Render según tipo ───────────────────────────────────────
function _renderPreview(pv) {
    const body = document.getElementById('pv-body');
    if (!body) return;

    if (pv.tipo === 'image') {
        const raw = `/api/nas/raw?path=${encodeURIComponent(pv.rel)}`;
        body.innerHTML = `
            <div class="pv-img-wrap">
                <img src="${raw}" alt="${escapeHtml(pv.nombre)}"
                     onclick="this.classList.toggle('pv-img-zoom')">
            </div>`;
        return;
    }

    if (pv.tipo === 'pdf') {
        const raw = `/api/nas/raw?path=${encodeURIComponent(pv.rel)}`;
        body.innerHTML = `<iframe class="pv-pdf" src="${raw}"></iframe>`;
        return;
    }

    if (pv.tipo === 'notebook') {
        const nb = pv.notebook || {};
        const celdas = (nb.celdas || []).map((c, i) => {
            const lang = nb.language || 'python';
            if (c.tipo === 'markdown') {
                return `<div class="nb-cell nb-md">${_mdMin(c.fuente)}</div>`;
            }
            const outputs = (c.outputs || []).map(o => {
                if (o.tipo === 'html') return `<div class="nb-out">${o.data}</div>`;
                if (o.tipo === 'error') return `<pre class="nb-out nb-err">${escapeHtml(o.data)}</pre>`;
                return `<pre class="nb-out">${escapeHtml(o.data)}</pre>`;
            }).join('');
            return `<div class="nb-cell nb-code">
                <div class="nb-in"><span class="nb-prompt">In [${i+1}]:</span>
                    <pre class="nb-src">${escapeHtml(c.fuente)}</pre></div>
                ${outputs ? `<div class="nb-out-wrap"><span class="nb-prompt">Out:</span>${outputs}</div>` : ''}
            </div>`;
        }).join('');
        body.innerHTML = `
            <div class="nb-meta">Kernel: <b>${escapeHtml(nb.kernel || '?')}</b> ·
                 Lenguaje: <b>${escapeHtml(nb.language || '?')}</b> ·
                 ${(nb.celdas || []).length} celdas</div>
            <div class="nb-render">${celdas || '<div class="empty">Notebook vacío</div>'}</div>`;
        return;
    }

    if (pv.tipo === 'csv') {
        const filas = pv.filas || [];
        if (!filas.length) { body.innerHTML = '<div class="empty">CSV vacío</div>'; return; }
        const cab = filas[0];
        const resto = filas.slice(1);
        body.innerHTML = `
            <div class="csv-meta">${resto.length} fila(s) · ${cab.length} columna(s) · delimitador: ${pv.delim}</div>
            <div class="csv-wrap"><table class="csv-tabla">
                <thead><tr>${cab.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
                <tbody>${resto.map(r => `<tr>${r.map(c => `<td>${escapeHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody>
            </table></div>
            ${pv.truncado ? '<div class="pv-nota">Mostrando primeras 100 filas (archivo truncado)</div>' : ''}`;
        return;
    }

    if (pv.tipo === 'text') {
        const lineas = (pv.texto || '').split('\n');
        const html = lineas.map((l, i) =>
            `<span class="pv-ln">${String(i+1).padStart(4)}</span>${escapeHtml(l) || ' '}`
        ).join('\n');
        const nota = pv.nota ? `<div class="pv-nota">${escapeHtml(pv.nota)}</div>` : '';
        body.innerHTML = `
            ${nota}
            <pre class="pv-texto">${html}</pre>
            ${pv.truncado ? '<div class="pv-nota">⚠ Archivo truncado a 500 KB</div>' : ''}`;
        return;
    }

    // binario
    body.innerHTML = `<div class="empty">
        <span data-ico="file"></span>
        <p style="margin-top:10px;">Sin vista previa para este tipo de archivo.</p>
        <p style="margin-top:6px;font-family:var(--mono);font-size:11px;">${escapeHtml(pv.nombre)} · ${_fmtSize(pv.size)}</p>
    </div>`;
}

// ─── Acciones del footer ─────────────────────────────────────
async function pvCopiarRuta(rel) {
    const abs = (_nasHome ? _nasHome + '/' + rel : rel);
    const ok = await copiarAlPortapapeles(abs);
    toast(ok ? 'Ruta copiada: ' + abs : 'No se pudo copiar', ok ? 'success' : 'error');
}

async function pvCopiarPython(rel) {
    const abs = (_nasHome ? _nasHome + '/' + rel : rel);
    const ok = await copiarAlPortapapeles(`"${abs}"`);
    toast(ok ? 'String Python copiado' : 'No se pudo copiar', ok ? 'success' : 'error');
}

function pvDescargar(rel, nombre) {
    const a = document.createElement('a');
    a.href = `/api/nas/download?path=${encodeURIComponent(rel)}`;
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 100);
}

// ─── Exponer ─────────────────────────────────────────────────
window.abrirPreview   = abrirPreview;
window.cerrarPreview  = cerrarPreview;
window.pvCopiarRuta   = pvCopiarRuta;
window.pvCopiarPython = pvCopiarPython;
window.pvDescargar    = pvDescargar;
