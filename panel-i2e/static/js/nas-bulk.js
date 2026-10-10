// ═══════════════════════════════════════════════════════════════
// Selección múltiple + acciones bulk en el NAS
// ═══════════════════════════════════════════════════════════════

let _seleccion = new Set();       // conjunto de rels
let _ultimoClick = null;          // para shift+click

function _bulkLimpiar() {
    _seleccion.clear();
    _ultimoClick = null;
    _bulkRefrescarUI();
}

function _bulkToggle(rel, shift) {
    if (shift && _ultimoClick && _ultimoClick !== rel) {
        // Seleccionar rango entre _ultimoClick y rel (en el orden visible actual)
        const visibles = Array.from(document.querySelectorAll('.nas-item[data-rel]'))
            .map(el => el.dataset.rel)
            .filter(r => r);
        const i1 = visibles.indexOf(_ultimoClick);
        const i2 = visibles.indexOf(rel);
        if (i1 !== -1 && i2 !== -1) {
            const [a, b] = i1 < i2 ? [i1, i2] : [i2, i1];
            for (let i = a; i <= b; i++) _seleccion.add(visibles[i]);
        }
    } else {
        if (_seleccion.has(rel)) _seleccion.delete(rel);
        else _seleccion.add(rel);
    }
    _ultimoClick = rel;
    _bulkRefrescarUI();
}

function _bulkRefrescarUI() {
    // Refrescar estado de checkboxes visibles
    document.querySelectorAll('.nas-item[data-rel]').forEach(el => {
        const rel = el.dataset.rel;
        const cb = el.querySelector('.nas-check input');
        if (cb) cb.checked = _seleccion.has(rel);
        el.classList.toggle('nas-sel', _seleccion.has(rel));
    });

    // Barra bulk
    let barra = document.getElementById('nas-bulk-bar');
    if (_seleccion.size === 0) {
        barra?.remove();
        // también quitar estado del select-all
        const sa = document.getElementById('nas-check-all');
        if (sa) sa.checked = false;
        return;
    }
    if (!barra) {
        barra = document.createElement('div');
        barra.id = 'nas-bulk-bar';
        barra.className = 'nas-bulk-bar';
        barra.innerHTML = `
            <span class="nas-bulk-count"><b id="nas-bulk-n">0</b> seleccionado(s)</span>
            <button class="btn btn-b" onclick="bulkCopiarRutas()">
                <span data-ico="copy"></span>Copiar rutas
            </button>
            <button class="btn btn-n" onclick="bulkCopiarPython()">
                <span data-ico="file-code"></span>Python
            </button>
            <button class="btn btn-n" onclick="bulkZip()">
                <span data-ico="download"></span>ZIP
            </button>
            <button class="btn btn-n" onclick="bulkMover()">
                <span data-ico="folder"></span>Mover a…
            </button>
            <button class="btn btn-r" onclick="bulkEliminar()">
                <span data-ico="trash"></span>Eliminar
            </button>
            <div style="flex:1;"></div>
            <button class="hdr-btn" onclick="_bulkLimpiar()" title="Limpiar selección">
                <span data-ico="x"></span>
            </button>`;
        document.getElementById('tab-nas')?.appendChild(barra);
    }
    document.getElementById('nas-bulk-n').textContent = _seleccion.size;
}

// ─── Acciones bulk ───────────────────────────────────────────
async function bulkCopiarRutas() {
    const rutas = Array.from(_seleccion).map(r => _nasHome + '/' + r).join('\n');
    const ok = await copiarAlPortapapeles(rutas);
    toast(ok ? `${_seleccion.size} ruta(s) copiada(s)` : 'No se pudo copiar',
          ok ? 'success' : 'error');
}

async function bulkCopiarPython() {
    const lines = Array.from(_seleccion).map(r => `"${_nasHome}/${r}"`).join(',\n');
    const ok = await copiarAlPortapapeles(`[\n${lines}\n]`);
    toast(ok ? 'Lista Python copiada' : 'No se pudo copiar', ok ? 'success' : 'error');
}

function bulkZip() {
    const lista = Array.from(_seleccion).join(',');
    const a = document.createElement('a');
    a.href = `/api/nas/download-zip-multi?paths=${encodeURIComponent(lista)}`;
    a.download = `seleccion_${_seleccion.size}_items.zip`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 100);
    toast(`Empaquetando ${_seleccion.size} items…`, 'info');
}

async function bulkEliminar() {
    if (!confirm(`¿Eliminar ${_seleccion.size} item(s)?\n\nNo se puede deshacer.`)) return;
    const paths = Array.from(_seleccion);
    try {
        const data = await api('/api/nas/delete-multiple', {
            method: 'POST',
            body: JSON.stringify({ paths })
        });
        if (data.status !== 'success') { toast('Error: ' + data.output, 'error'); return; }
        const ok = data.eliminados?.length || 0;
        const ko = data.errores?.length || 0;
        toast(`Eliminados: ${ok}${ko ? ' · Errores: ' + ko : ''}`,
              ko ? 'warning' : 'success');
        _bulkLimpiar();
        cargarNas();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function bulkMover() {
    if (_seleccion.size === 0) return;
    const destino = prompt(
        `Mover ${_seleccion.size} item(s) a (ruta relativa desde el home):`,
        ""
    );
    if (destino === null) return;

    const paths = Array.from(_seleccion);
    try {
        const data = await api('/api/nas/move', {
            method: 'POST',
            body: JSON.stringify({ paths, destino: destino.trim() })
        });
        if (data.status !== 'success') { toast('Error: ' + data.output, 'error'); return; }
        const ok = data.movidos?.length || 0;
        const ko = data.errores?.length || 0;
        toast(`Movidos: ${ok}${ko ? ' · Errores: ' + ko : ''}`,
              ko ? 'warning' : 'success');
        _bulkLimpiar();
        cargarNas();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Integración con la lista (hook en nas.js) ───────────────
// Envolvemos _renderLista para añadir checkbox y manejar eventos
const _origRenderLista = window._renderLista || _renderLista;
function _renderListaConBulk() {
    _origRenderLista.apply(this, arguments);

    const lista = document.getElementById('nas-lista');
    if (!lista) return;

    // Añadir checkbox a cada fila
    lista.querySelectorAll('.nas-item').forEach(row => {
        if (row.classList.contains('nas-up')) return;
        if (row.querySelector('.nas-check')) return;   // ya tiene

        const rel = row.dataset.rel;
        const esDir = row.dataset.dir === '1';

        const cb = document.createElement('span');
        cb.className = 'nas-check';
        cb.innerHTML = `<input type="checkbox">`;
        const input = cb.querySelector('input');
        input.checked = _seleccion.has(rel);

        input.addEventListener('click', e => {
            e.stopPropagation();
            _bulkToggle(rel, e.shiftKey);
        });
        cb.addEventListener('click', e => e.stopPropagation());

        row.insertBefore(cb, row.firstChild);

        // Alt+Click en el nombre → abre preview
        const nombre = row.querySelector('.nas-nombre');
        if (nombre && !esDir) {
            nombre.addEventListener('click', e => {
                if (e.altKey) {
                    e.preventDefault(); e.stopPropagation();
                    abrirPreview({ rel, nombre: rel.split('/').pop() });
                }
            });
        }
        // Doble click en archivo → preview en vez de descargar
        row.addEventListener('dblclick', e => {
            if (!esDir) {
                e.preventDefault(); e.stopPropagation();
                abrirPreview({ rel, nombre: rel.split('/').pop() });
            }
        }, true);

        row.classList.toggle('nas-sel', _seleccion.has(rel));
    });

    // Cabecera select-all
    _actualizarSelectAllCabecera();
    _bulkRefrescarUI();
}

function _actualizarSelectAllCabecera() {
    const hr = document.querySelector('.nas-header-row');
    if (!hr) return;
    if (hr.querySelector('.nas-h-check')) return;

    const span = document.createElement('span');
    span.className = 'nas-h-check';
    span.innerHTML = `<input type="checkbox" id="nas-check-all" title="Seleccionar todo">`;
    hr.insertBefore(span, hr.firstChild);

    span.querySelector('input').addEventListener('change', e => {
        const marcar = e.target.checked;
        document.querySelectorAll('.nas-item[data-rel]').forEach(row => {
            if (row.classList.contains('nas-up')) return;
            const rel = row.dataset.rel;
            if (marcar) _seleccion.add(rel);
            else        _seleccion.delete(rel);
        });
        _bulkRefrescarUI();
    });
}

// ─── Arranque ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Reemplazar la función global por la envuelta
    if (typeof window._renderLista === 'undefined' && typeof _renderLista !== 'undefined') {
        window._renderLista = _renderLista;
        // Trick: redefinimos la referencia dentro de cargarNas
        // (nas.js llama a _renderLista como función global)
    }
    // Sobreescribir en window
    window._renderListaOrig = window._renderLista;
    window._renderLista = _renderListaConBulk;
    // El archivo nas.js llama a _renderLista() dentro de su scope,
    // así que también parcheamos ahí si es necesario (fallback: hook en
    // document con MutationObserver sobre #nas-lista)
    const lista = document.getElementById('nas-lista');
    if (lista) {
        const mo = new MutationObserver(() => {
            // Cuando cambia el contenido, aseguramos checkboxes
            clearTimeout(window._bulkHookT);
            window._bulkHookT = setTimeout(() => {
                if (lista.querySelector('.nas-item') && !lista.querySelector('.nas-check')) {
                    _renderListaConBulk.call(null);
                }
            }, 50);
        });
        mo.observe(lista, { childList: true, subtree: false });
    }
});

// ─── Exponer ─────────────────────────────────────────────────
window._bulkLimpiar     = _bulkLimpiar;
window.bulkCopiarRutas  = bulkCopiarRutas;
window.bulkCopiarPython = bulkCopiarPython;
window.bulkZip          = bulkZip;
window.bulkEliminar     = bulkEliminar;
window.bulkMover        = bulkMover;
