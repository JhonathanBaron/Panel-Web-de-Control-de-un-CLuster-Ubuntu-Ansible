// ═══════════════════════════════════════════════════════════════
// Editor de playbooks — ver, editar, crear, eliminar, backups
// ═══════════════════════════════════════════════════════════════

let _pbActual = null;          // { nombre, contenido, mtime, size }
let _pbDirty  = false;

// ─── Aviso si hay cambios sin guardar ────────────────────────
window.addEventListener('beforeunload', e => {
    if (_pbDirty && document.getElementById('modal-pb-editor')) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// ─── Abrir editor con el playbook seleccionado ───────────────
async function editarPlaybookSeleccionado() {
    const sel = document.getElementById('pb-select');
    const nombre = sel?.value;
    if (!nombre) { toast('Selecciona un playbook primero', 'warning'); return; }
    await abrirEditorPlaybook(nombre);
}

// ─── Abrir editor para un playbook concreto ──────────────────
async function abrirEditorPlaybook(nombre) {
    try {
        const data = await api(`/api/playbooks/leer?nombre=${encodeURIComponent(nombre)}`);
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error');
            return;
        }
        _pbActual = data;
        _pbDirty  = false;
        _renderEditor(data.nombre, data.contenido, data.mtime, data.size, false);
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ─── Abrir editor para un playbook NUEVO ─────────────────────
function nuevoPlaybook() {
    const plantilla = `---
# Playbook creado desde el panel I2E
- name: Mi nuevo playbook
  hosts: compute
  become: false
  gather_facts: true
  tasks:
    - name: Ejemplo — ver uptime
      ansible.builtin.command: uptime
      register: out
      changed_when: false

    - name: Mostrar resultado
      ansible.builtin.debug:
        var: out.stdout
`;
    _pbActual = { nombre: "", contenido: plantilla, mtime: "", size: plantilla.length };
    _pbDirty = true;
    _renderEditor("", plantilla, "", plantilla.length, true);
}

// ─── Render del modal ────────────────────────────────────────
function _renderEditor(nombre, contenido, mtime, size, esNuevo) {
    document.getElementById('modal-pb-editor')?.remove();

    const html = `
        <div class="modal-bg show" id="modal-pb-editor">
            <div class="modal modal-pb">
                <div class="pb-editor-head">
                    <h3>
                        <span data-ico="book"></span>
                        ${esNuevo ? 'Nuevo playbook' : 'Editar playbook'}
                    </h3>
                    <button class="hdr-btn" onclick="cerrarEditorPlaybook()" title="Cerrar">
                        <span data-ico="x"></span>
                    </button>
                </div>

                <div class="pb-editor-meta">
                    <div class="pb-editor-nombre">
                        <label>Nombre del archivo</label>
                        <input type="text" id="pb-edit-nombre"
                               value="${escapeHtml(nombre)}"
                               placeholder="mi_playbook.yml"
                               ${esNuevo ? '' : 'readonly'}>
                    </div>
                    <div class="pb-editor-info">
                        ${mtime ? `<div><b>Modificado:</b> ${escapeHtml(mtime)}</div>` : ''}
                        <div><b>Tamaño:</b> <span id="pb-edit-size">${size}</span> bytes</div>
                        <div id="pb-edit-dirty" class="pb-dirty oculto">● sin guardar</div>
                    </div>
                </div>

                <div class="pb-editor-toolbar">
                    <button class="btn btn-n" onclick="pbInsertarTexto('---\\n')" title="Documento YAML">
                        ---
                    </button>
                    <button class="btn btn-n" onclick="pbInsertarTexto('- name: Tarea\\n  ansible.builtin.command: echo hola\\n  changed_when: false\\n')"
                            title="Añadir tarea">
                        + tarea
                    </button>
                    <button class="btn btn-n" onclick="pbFormatearYaml()" title="Ordenar y validar YAML">
                        <span data-ico="refresh"></span> Formatear
                    </button>
                    <button class="btn btn-n" onclick="pbMostrarBackups()" ${esNuevo ? 'disabled' : ''}>
                        <span data-ico="folder"></span> Backups
                    </button>
                    <span class="pb-editor-lineno" id="pb-lineno">1:1</span>
                </div>

                <div class="pb-editor-wrap">
                    <div class="pb-linenums" id="pb-linenums"></div>
                    <textarea id="pb-edit-textarea" spellcheck="false"
                              placeholder="Escribe aquí tu playbook YAML...">${escapeHtml(contenido)}</textarea>
                </div>

                <div class="pb-editor-footer">
                    <span class="pb-editor-status" id="pb-edit-status"></span>
                    <div class="modal-actions" style="margin:0;">
                        ${esNuevo ? '' :
                            `<button class="btn btn-r" onclick="eliminarPlaybook('${escapeHtml(nombre)}')">
                                <span data-ico="trash"></span>Eliminar
                            </button>`}
                        <button class="btn btn-n" onclick="cerrarEditorPlaybook()">Cancelar</button>
                        <button class="btn btn-g" onclick="guardarPlaybook()">
                            <span data-ico="play"></span>${esNuevo ? 'Crear' : 'Guardar'}
                        </button>
                    </div>
                </div>
            </div>
        </div>`;

    document.body.insertAdjacentHTML('beforeend', html);

    const ta = document.getElementById('pb-edit-textarea');
    ta.addEventListener('input', _pbOnInput);
    ta.addEventListener('keydown', _pbOnKey);
    ta.addEventListener('scroll', _pbSyncScroll);
    ta.addEventListener('click', _pbSyncCursor);
    ta.addEventListener('keyup', _pbSyncCursor);
    ta.focus();
    _pbSyncLineNumbers();
    _pbSyncCursor();
}

// ─── Eventos del textarea ────────────────────────────────────
function _pbOnInput() {
    _pbDirty = true;
    document.getElementById('pb-edit-dirty')?.classList.remove('oculto');
    document.getElementById('pb-edit-size').textContent =
        new Blob([document.getElementById('pb-edit-textarea').value]).size;
    _pbSyncLineNumbers();
    _pbSyncCursor();
    _pbValidarYamlLocal();
}

function _pbOnKey(e) {
    const ta = e.target;
    // Tab inserta 2 espacios en vez de perder el foco
    if (e.key === 'Tab') {
        e.preventDefault();
        const s = ta.selectionStart, en = ta.selectionEnd;
        ta.value = ta.value.substring(0, s) + '  ' + ta.value.substring(en);
        ta.selectionStart = ta.selectionEnd = s + 2;
        _pbOnInput();
    }
    // Ctrl+S guarda
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        guardarPlaybook();
    }
    // Escape cierra (con confirmación si hay cambios)
    if (e.key === 'Escape') {
        e.preventDefault();
        cerrarEditorPlaybook();
    }
}

function _pbSyncScroll() {
    const ta = document.getElementById('pb-edit-textarea');
    const ln = document.getElementById('pb-linenums');
    if (ta && ln) ln.scrollTop = ta.scrollTop;
}

function _pbSyncCursor() {
    const ta = document.getElementById('pb-edit-textarea');
    const el = document.getElementById('pb-lineno');
    if (!ta || !el) return;
    const pos = ta.selectionStart;
    const antes = ta.value.substring(0, pos);
    const linea = antes.split('\n').length;
    const col = pos - antes.lastIndexOf('\n');
    el.textContent = `${linea}:${col}`;
}

function _pbSyncLineNumbers() {
    const ta = document.getElementById('pb-edit-textarea');
    const ln = document.getElementById('pb-linenums');
    if (!ta || !ln) return;
    const n = ta.value.split('\n').length;
    ln.innerHTML = Array.from({length: n}, (_, i) => i + 1).join('<br>');
}

// ─── Validación YAML en vivo (básica) ────────────────────────
function _pbValidarYamlLocal() {
    const ta = document.getElementById('pb-edit-textarea');
    const st = document.getElementById('pb-edit-status');
    if (!ta || !st) return;
    const txt = ta.value;
    // Heurística muy simple: buscar tabs (YAML no los permite)
    if (txt.includes('\t')) {
        st.textContent = '⚠ Contiene tabuladores (usa espacios)';
        st.className = 'pb-editor-status err';
    } else if (!txt.trim()) {
        st.textContent = '⚠ Vacío';
        st.className = 'pb-editor-status warn';
    } else {
        st.textContent = '✓ Validación básica OK (el servidor hará la completa al guardar)';
        st.className = 'pb-editor-status ok';
    }
}

// ─── Utilidades toolbar ──────────────────────────────────────
function pbInsertarTexto(txt) {
    const ta = document.getElementById('pb-edit-textarea');
    if (!ta) return;
    const s = ta.selectionStart, en = ta.selectionEnd;
    ta.value = ta.value.substring(0, s) + txt + ta.value.substring(en);
    ta.selectionStart = ta.selectionEnd = s + txt.length;
    ta.focus();
    _pbOnInput();
}

async function pbFormatearYaml() {
    const ta = document.getElementById('pb-edit-textarea');
    if (!ta) return;
    // Validación simple + limpieza de tabs
    ta.value = ta.value.replace(/\t/g, '  ');
    toast('Formateado (tabs → espacios). La validación real la hace el servidor.', 'info');
    _pbOnInput();
}

// ─── Guardar (crear o actualizar) ────────────────────────────
async function guardarPlaybook() {
    const ta = document.getElementById('pb-edit-textarea');
    const inp = document.getElementById('pb-edit-nombre');
    if (!ta || !inp) return;

    const nombre = inp.value.trim();
    const contenido = ta.value;
    const esNuevo = !!inp.readOnly === false && (!_pbActual?.nombre);

    if (!nombre) { toast('Falta el nombre del archivo', 'warning'); return; }

    const endpoint = esNuevo ? '/api/playbooks/crear' : '/api/playbooks/guardar';

    try {
        const data = await api(endpoint, {
            method: 'POST',
            body: JSON.stringify({ nombre, contenido })
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error');
            document.getElementById('pb-edit-status').textContent = '✗ ' + (data.output || '');
            document.getElementById('pb-edit-status').className = 'pb-editor-status err';
            return;
        }
        toast(data.output, 'success');
        _pbDirty = false;
        cerrarEditorPlaybook(true);
        cargarPlaybooks();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ─── Eliminar ────────────────────────────────────────────────
async function eliminarPlaybook(nombre) {
    if (!confirm(`¿Eliminar ${nombre}?\n\nSe guardará un backup por si quieres restaurar.`)) return;
    try {
        const data = await api(`/api/playbooks/${encodeURIComponent(nombre)}`, { method: 'DELETE' });
        if (data.status !== 'success') { toast('Error: ' + data.output, 'error'); return; }
        toast('Eliminado (backup guardado)', 'success');
        _pbDirty = false;
        cerrarEditorPlaybook(true);
        cargarPlaybooks();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ─── Backups ─────────────────────────────────────────────────
async function pbMostrarBackups() {
    const nombre = _pbActual?.nombre;
    if (!nombre) return;
    try {
        const data = await api(`/api/playbooks/${encodeURIComponent(nombre)}/backups`);
        const backups = data.backups || [];
        const html = `
            <div class="modal-bg show" id="modal-pb-backups" style="z-index:1100;"
                 onclick="if(event.target===this)this.remove()">
                <div class="modal">
                    <h3><span data-ico="folder"></span> Backups de ${escapeHtml(nombre)}</h3>
                    ${backups.length === 0
                        ? '<div class="empty">Sin backups todavía</div>'
                        : `<table class="tabla">
                            <thead><tr><th>Fecha</th><th>Tamaño</th><th></th></tr></thead>
                            <tbody>
                                ${backups.map(b => `
                                    <tr>
                                        <td style="font-family:var(--mono);font-size:12px;">${escapeHtml(b.mtime)}</td>
                                        <td>${b.size} b</td>
                                        <td>
                                            <button class="btn btn-b"
                                                    onclick="pbRestaurarBackup('${escapeHtml(nombre)}','${escapeHtml(b.nombre)}')">
                                                Restaurar
                                            </button>
                                        </td>
                                    </tr>`).join('')}
                            </tbody>
                           </table>`}
                    <div class="modal-actions">
                        <button class="btn btn-n" onclick="document.getElementById('modal-pb-backups').remove()">
                            Cerrar
                        </button>
                    </div>
                </div>
            </div>`;
        document.getElementById('modal-pb-backups')?.remove();
        document.body.insertAdjacentHTML('beforeend', html);
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

async function pbRestaurarBackup(nombre, backup) {
    if (!confirm(`¿Restaurar ${backup}?\n\nEl actual se guardará como backup.`)) return;
    try {
        const data = await api(`/api/playbooks/${encodeURIComponent(nombre)}/restore`, {
            method: 'POST',
            body: JSON.stringify({ backup })
        });
        if (data.status !== 'success') { toast('Error: ' + data.output, 'error'); return; }
        toast('Restaurado', 'success');
        document.getElementById('modal-pb-backups')?.remove();
        await abrirEditorPlaybook(nombre);   // recargar contenido
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ─── Cerrar editor ───────────────────────────────────────────
function cerrarEditorPlaybook(sinConfirmar = false) {
    if (!sinConfirmar && _pbDirty) {
        if (!confirm('Hay cambios sin guardar. ¿Cerrar de todas formas?')) return;
    }
    document.getElementById('modal-pb-editor')?.remove();
    _pbActual = null;
    _pbDirty  = false;
}

// Exponer
window.nuevoPlaybook              = nuevoPlaybook;
window.editarPlaybookSeleccionado = editarPlaybookSeleccionado;
window.abrirEditorPlaybook        = abrirEditorPlaybook;
window.guardarPlaybook            = guardarPlaybook;
window.eliminarPlaybook           = eliminarPlaybook;
window.cerrarEditorPlaybook       = cerrarEditorPlaybook;
window.pbInsertarTexto            = pbInsertarTexto;
window.pbFormatearYaml            = pbFormatearYaml;
window.pbMostrarBackups           = pbMostrarBackups;
window.pbRestaurarBackup          = pbRestaurarBackup;
