// ═══════════════════════════════════════════════════════════════
// Editor de inventario Ansible
// ═══════════════════════════════════════════════════════════════

var _invData = { grupos: {}, orden: [] };
var _invDirty = false;
var _invPath  = '';

// ─── Carga principal ─────────────────────────────────────────
async function invCargar() {
    var editor = document.getElementById('inv-editor');
    if (!editor) return;

    try {
        var raw = await api('/api/inventory/raw');
        if (raw.status !== 'success') throw new Error(raw.output || 'error');
        _invPath = raw.path || '';
        editor.value = raw.contenido || '';
        var pathEl = document.getElementById('inv-path');
        if (pathEl) pathEl.textContent = _invPath;
        _invDirty = false;
        _invActualizarDirty();
        await invRecargarArbol();
        invValidar();
    } catch (e) {
        toast('Error cargando inventario: ' + e.message, 'error');
    }
}

async function invRecargar() {
    if (_invDirty && !confirm('Hay cambios sin guardar. ¿Recargar de todas formas?')) return;
    await invCargar();
    toast('Recargado', 'info', 1500);
}

async function invRecargarArbol() {
    var cont = document.getElementById('inv-arbol');
    if (!cont) return;
    cont.innerHTML = '<div class="empty"><span class="spin"></span> Cargando…</div>';

    try {
        var data = await api('/api/inventory/parsed');
        if (data.status !== 'success') throw new Error(data.output || 'error');
        _invData = data;
        invRenderArbol(data);
    } catch (e) {
        cont.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + '</div>';
    }
}

// ─── Render del árbol ────────────────────────────────────────
function invRenderArbol(data) {
    var cont = document.getElementById('inv-arbol');
    if (!cont) return;

    var grupos = data.grupos || {};
    var orden = data.orden || [];
    var html = '';

    for (var i = 0; i < orden.length; i++) {
        var nombre = orden[i];
        var g = grupos[nombre];
        if (!g) continue;

        var tipo = g.tipo || 'normal';
        var iconoTipo = tipo === 'children' ? 'users' : (tipo === 'vars' ? 'wrench' : 'folder');
        var nItems = (g.hosts || []).length + (g.children || []).length + Object.keys(g.vars || {}).length;

        html += '<div class="inv-grupo">';
        html += '<div class="inv-grupo-head" onclick="invToggleGrupo(this)">';
        html += '  <span data-ico="' + iconoTipo + '"></span>';
        html += '  <b>[' + escapeHtml(nombre) + ']</b>';
        html += '  <span class="inv-grupo-tipo">' + tipo + '</span>';
        html += '  <span class="inv-grupo-count">' + nItems + '</span>';
        html += '  <span class="arr">▾</span>';
        html += '</div>';
        html += '<div class="inv-grupo-body">';

        // Hosts
        for (var j = 0; j < (g.hosts || []).length; j++) {
            var h = g.hosts[j];
            var varsTxt = Object.keys(h.vars || {}).length
                ? Object.keys(h.vars).map(function(k){ return k + '=' + h.vars[k]; }).join(' ')
                : '';
            html += '<div class="inv-host" data-ip="' + escapeHtml(h.ip) + '" data-grupo="' + escapeHtml(nombre) + '"';
            html += ' ondblclick="invEditarNodo(\'' + escapeHtml(h.ip) + '\')"';
            html += ' title="Doble-click para editar">';
            html += '  <span data-ico="globe"></span>';
            html += '  <span class="inv-host-ip">' + escapeHtml(h.ip) + '</span>';
            if (varsTxt) html += '  <span class="inv-host-vars">' + escapeHtml(varsTxt) + '</span>';
            html += '  <button class="inv-btn-del" onclick="event.stopPropagation();invEliminarNodo(\'' + escapeHtml(h.ip) + '\')" title="Eliminar de todo el inventario">';
            html += '    <span data-ico="trash"></span>';
            html += '  </button>';
            html += '</div>';
        }

        // Children
        for (var k = 0; k < (g.children || []).length; k++) {
            html += '<div class="inv-child">';
            html += '  <span data-ico="users"></span>';
            html += '  <span>' + escapeHtml(g.children[k]) + '</span>';
            html += '</div>';
        }

        // Vars
        var varsKeys = Object.keys(g.vars || {});
        for (var v = 0; v < varsKeys.length; v++) {
            html += '<div class="inv-var">';
            html += '  <span data-ico="wrench"></span>';
            html += '  <b>' + escapeHtml(varsKeys[v]) + '</b>';
            html += '  <span>= ' + escapeHtml(g.vars[varsKeys[v]]) + '</span>';
            html += '</div>';
        }

        html += '</div></div>';
    }

    if (!html) html = '<div class="empty">Inventario vacío</div>';
    cont.innerHTML = html;
}

function invToggleGrupo(head) {
    var body = head.nextElementSibling;
    if (!body) return;
    var oculto = body.style.display === 'none';
    body.style.display = oculto ? '' : 'none';
    head.classList.toggle('plegado', !oculto);
}

// ─── Editor raw ──────────────────────────────────────────────
function invOnInput() {
    _invDirty = true;
    _invActualizarDirty();
    invValidar();
}

function _invActualizarDirty() {
    var el = document.getElementById('inv-dirty');
    if (!el) return;
    el.classList.toggle('oculto', !_invDirty);
}

async function invValidar() {
    var editor = document.getElementById('inv-editor');
    var st = document.getElementById('inv-status');
    if (!editor || !st) return;

    try {
        var data = await api('/api/inventory/validate', {
            method: 'POST',
            body: JSON.stringify({ contenido: editor.value })
        });
        var errs = data.errores || [];
        var warns = data.warnings || [];
        if (errs.length) {
            st.className = 'inv-status err';
            st.textContent = '✗ ' + errs.length + ' error(es): ' + errs[0];
        } else if (warns.length) {
            st.className = 'inv-status warn';
            st.textContent = '⚠ ' + warns.length + ' aviso(s): ' + warns[0];
        } else {
            st.className = 'inv-status ok';
            st.textContent = '✓ Inventario válido';
        }
    } catch (e) {
        st.className = 'inv-status err';
        st.textContent = '✗ Error validando: ' + e.message;
    }
}

// ─── Guardar ─────────────────────────────────────────────────
async function invGuardar() {
    var editor = document.getElementById('inv-editor');
    if (!editor) return;

    if (!_invDirty) {
        toast('Sin cambios que guardar', 'info', 1500);
        return;
    }

    toast('Guardando…', 'info', 2000);
    try {
        var data = await api('/api/inventory/save', {
            method: 'POST',
            body: JSON.stringify({ contenido: editor.value })
        });
        if (data.status !== 'success') {
            var extra = data.errores ? '\n\n' + data.errores.join('\n') : '';
            toast('Error: ' + (data.output || '') + extra, 'error', 8000);
            return;
        }
        _invDirty = false;
        _invActualizarDirty();
        var msg = 'Guardado ✓';
        if (data.backup) msg += ' (backup: ' + data.backup + ')';
        toast(msg, 'success');
        if (data.warnings && data.warnings.length) {
            console.warn('Warnings:', data.warnings);
        }
        await invRecargarArbol();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ─── Añadir nodo ─────────────────────────────────────────────
function invAñadirNodo() {
    var grupos = Object.keys(_invData.grupos || {}).filter(function(g){
        return _invData.grupos[g].tipo === 'normal';
    });

    var checksHtml = grupos.map(function(g){
        return '<label style="display:block;margin-bottom:4px;">' +
               '<input type="checkbox" name="inv-g" value="' + escapeHtml(g) + '"> ' +
               escapeHtml(g) + '</label>';
    }).join('');

    var html = ''
        + '<div class="modal-bg show" id="modal-inv-nodo" onclick="if(event.target===this)invCerrarModal()">'
        + '  <div class="modal">'
        + '    <h3><span data-ico="plus"></span> Añadir nodo al inventario</h3>'
        + '    <div class="form-group"><label>IP o hostname</label>'
        + '      <input type="text" id="inv-n-ip" placeholder="10.4.8.20"></div>'
        + '    <div class="form-group"><label>Grupos (marca al menos uno)</label>'
        + '      <div style="max-height:180px;overflow:auto;border:1px solid var(--border);padding:8px;border-radius:6px;">'
        + checksHtml + '</div>'
        + '    </div>'
        + '    <div class="form-group"><label>Variables (opcional)</label>'
        + '      <input type="text" id="inv-n-user" placeholder="ansible_user=clusterX" style="font-family:var(--mono);"></div>'
        + '    <div class="modal-actions">'
        + '      <button class="btn btn-n" onclick="invCerrarModal()">Cancelar</button>'
        + '      <button class="btn btn-g" onclick="invCrearNodo()">Añadir</button>'
        + '    </div>'
        + '  </div>'
        + '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
    var inp = document.getElementById('inv-n-ip');
    if (inp) inp.focus();
}

function invCerrarModal() {
    var m = document.getElementById('modal-inv-nodo');
    if (m) m.remove();
    var m2 = document.getElementById('modal-inv-backups');
    if (m2) m2.remove();
}

async function invCrearNodo() {
    var ip = document.getElementById('inv-n-ip').value.trim();
    var varsTxt = document.getElementById('inv-n-user').value.trim();
    var grupos = Array.from(document.querySelectorAll('input[name="inv-g"]:checked'))
                      .map(function(x){ return x.value; });

    if (!ip) { toast('Falta la IP', 'warning'); return; }
    if (!grupos.length) { toast('Marca al menos un grupo', 'warning'); return; }

    var vars_ = {};
    if (varsTxt) {
        varsTxt.split(/\s+/).forEach(function(kv){
            if (kv.indexOf('=') > 0) {
                var p = kv.split('=');
                vars_[p[0]] = p.slice(1).join('=');
            }
        });
    }

    try {
        var data = await api('/api/inventory/nodo', {
            method: 'POST',
            body: JSON.stringify({ ip: ip, grupos: grupos, vars: vars_ })
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error', 6000);
            return;
        }
        toast(data.output + ' ✓', 'success');
        invCerrarModal();
        await invRecargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Editar nodo ─────────────────────────────────────────────
function invEditarNodo(ip) {
    // Buscar el nodo y sus datos
    var encontrado = null;
    var gruposDelNodo = [];
    var gruposTodos = Object.keys(_invData.grupos || {});
    gruposTodos.forEach(function(g) {
        var gg = _invData.grupos[g];
        if (gg.tipo !== 'normal') return;
        (gg.hosts || []).forEach(function(h) {
            if (h.ip === ip) {
                if (!encontrado) encontrado = h;
                gruposDelNodo.push(g);
            }
        });
    });

    if (!encontrado) {
        toast('Nodo no encontrado', 'warning');
        return;
    }

    var varsTxt = Object.keys(encontrado.vars || {})
        .map(function(k){ return k + '=' + encontrado.vars[k]; }).join(' ');

    var checksHtml = gruposTodos.filter(function(g){
        return _invData.grupos[g].tipo === 'normal';
    }).map(function(g){
        var chk = gruposDelNodo.indexOf(g) !== -1 ? ' checked' : '';
        return '<label style="display:block;margin-bottom:4px;">' +
               '<input type="checkbox" name="inv-e-g" value="' + escapeHtml(g) + '"' + chk + '> ' +
               escapeHtml(g) + '</label>';
    }).join('');

    var html = ''
        + '<div class="modal-bg show" id="modal-inv-nodo" onclick="if(event.target===this)invCerrarModal()">'
        + '  <div class="modal">'
        + '    <h3><span data-ico="pencil"></span> Editar ' + escapeHtml(ip) + '</h3>'
        + '    <div class="form-group"><label>Grupos</label>'
        + '      <div style="max-height:180px;overflow:auto;border:1px solid var(--border);padding:8px;border-radius:6px;">'
        + checksHtml + '</div>'
        + '    </div>'
        + '    <div class="form-group"><label>Variables (k=v separadas por espacios)</label>'
        + '      <input type="text" id="inv-e-vars" value="' + escapeHtml(varsTxt) + '" style="font-family:var(--mono);"></div>'
        + '    <div class="modal-actions">'
        + '      <button class="btn btn-n" onclick="invCerrarModal()">Cancelar</button>'
        + '      <button class="btn btn-g" onclick="invGuardarNodo(\'' + escapeHtml(ip) + '\')">Guardar</button>'
        + '    </div>'
        + '  </div>'
        + '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
}

async function invGuardarNodo(ip) {
    var varsTxt = document.getElementById('inv-e-vars').value.trim();
    var grupos = Array.from(document.querySelectorAll('input[name="inv-e-g"]:checked'))
                      .map(function(x){ return x.value; });

    var vars_ = {};
    if (varsTxt) {
        varsTxt.split(/\s+/).forEach(function(kv){
            if (kv.indexOf('=') > 0) {
                var p = kv.split('=');
                vars_[p[0]] = p.slice(1).join('=');
            }
        });
    }

    try {
        var data = await api('/api/inventory/nodo/' + encodeURIComponent(ip), {
            method: 'PUT',
            body: JSON.stringify({ vars: vars_, grupos: grupos })
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error', 6000);
            return;
        }
        toast('Actualizado ✓', 'success');
        invCerrarModal();
        await invRecargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Eliminar nodo ───────────────────────────────────────────
async function invEliminarNodo(ip) {
    if (!confirm('¿Eliminar ' + ip + ' de TODO el inventario?\n\nSe guardará un backup automáticamente.')) return;
    try {
        var data = await api('/api/inventory/nodo/' + encodeURIComponent(ip), { method: 'DELETE' });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error', 6000);
            return;
        }
        toast(ip + ' eliminado', 'success');
        await invRecargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Backups ─────────────────────────────────────────────────
async function invVerBackups() {
    try {
        var data = await api('/api/inventory/backups');
        var backups = data.backups || [];

        var filas = backups.length ? backups.map(function(b){
            return '<tr>'
                + '<td style="font-family:var(--mono);font-size:12px;">' + escapeHtml(b.mtime) + '</td>'
                + '<td>' + b.size + ' b</td>'
                + '<td><button class="btn btn-n" style="padding:3px 9px;font-size:11px;" '
                + 'onclick="invRestaurar(\'' + escapeHtml(b.nombre) + '\')">Restaurar</button></td>'
                + '</tr>';
        }).join('') : '<tr><td colspan="3" class="empty">Sin backups</td></tr>';

        var html = ''
            + '<div class="modal-bg show" id="modal-inv-backups" onclick="if(event.target===this)invCerrarModal()">'
            + '  <div class="modal" style="max-width:600px;">'
            + '    <h3><span data-ico="folder"></span> Backups del inventario</h3>'
            + '    <p style="font-size:12px;color:var(--dim);margin-bottom:12px;">'
            + '      Se guarda uno automáticamente antes de cada modificación. Máximo 30.</p>'
            + '    <table class="tabla">'
            + '      <thead><tr><th>Fecha</th><th>Tamaño</th><th></th></tr></thead>'
            + '      <tbody>' + filas + '</tbody>'
            + '    </table>'
            + '    <div class="modal-actions">'
            + '      <button class="btn btn-n" onclick="invCerrarModal()">Cerrar</button>'
            + '    </div>'
            + '  </div>'
            + '</div>';
        document.body.insertAdjacentHTML('beforeend', html);
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function invRestaurar(nombre) {
    if (!confirm('¿Restaurar el inventario desde ' + nombre + '?\n\nEl actual se guardará como backup.')) return;
    try {
        var data = await api('/api/inventory/restore', {
            method: 'POST',
            body: JSON.stringify({ nombre: nombre })
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error', 6000);
            return;
        }
        toast('Restaurado ✓', 'success');
        invCerrarModal();
        await invRecargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Arranque ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
    var tab = document.querySelector('.tab[data-tab="inventario"]');
    if (tab) {
        tab.addEventListener('click', function() {
            if (!document.getElementById('inv-editor')?.value) invCargar();
        });
    }
    if (tab && tab.classList.contains('activo')) invCargar();

    // Ctrl+S guarda
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
            var activo = document.querySelector('.tab[data-tab="inventario"]');
            if (activo && activo.classList.contains('activo')) {
                e.preventDefault();
                invGuardar();
            }
        }
    });
});

window.invCargar        = invCargar;
window.invRecargar      = invRecargar;
window.invRecargarArbol = invRecargarArbol;
window.invRenderArbol   = invRenderArbol;
window.invToggleGrupo   = invToggleGrupo;
window.invOnInput       = invOnInput;
window.invValidar       = invValidar;
window.invGuardar       = invGuardar;
window.invAñadirNodo    = invAñadirNodo;
window.invCerrarModal   = invCerrarModal;
window.invCrearNodo     = invCrearNodo;
window.invEditarNodo    = invEditarNodo;
window.invGuardarNodo   = invGuardarNodo;
window.invEliminarNodo  = invEliminarNodo;
window.invVerBackups    = invVerBackups;
window.invRestaurar     = invRestaurar;
