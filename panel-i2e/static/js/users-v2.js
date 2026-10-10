// ═══════════════════════════════════════════════════════════════
// Gestión de usuarios — un usuario = un acceso (PAM + users.yaml)
// ═══════════════════════════════════════════════════════════════

let _usrData = { users: [], resumen: {} };

// ─── Carga ───────────────────────────────────────────────────
async function usrCargar(autoSync = false) {
    // Gate por rol: solo admin puede ver/gestionar usuarios del clúster
    if (window.ROL_ACTUAL !== 'admin') {
        console.warn('[users] ignorado: rol actual no es admin');
        return;
    }
    const tbody = document.getElementById('usr-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" class="empty"><span class="spin"></span> Cargando…</td></tr>';

    // Auto-import silencioso la primera vez que se abre la tab
    if (autoSync) {
        try {
            const s = await api('/api/usuarios/auto-sync', { method: 'POST' });
            if (s.status === 'success' && s.n > 0) {
                toast(`Importados ${s.n} usuario(s) del sistema`, 'info', 3000);
            }
        } catch (e) { /* silencio */ }
    }

    try {
        const data = await api('/api/usuarios/v2');
        if (data.status !== 'success') throw new Error(data.output || 'error');
        _usrData = data;
        _usrRenderResumen();
        usrRender();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function _usrRenderResumen() {
    const cont = document.getElementById('usr-resumen');
    if (!cont) return;
    const r = _usrData.resumen || {};
    cont.innerHTML = `
        <div class="rsm-item"><div class="rsm-lbl">Total</div><div class="rsm-val">${r.total || 0}</div></div>
        <div class="rsm-item"><div class="rsm-lbl">En sistema</div><div class="rsm-val on">${r.en_sistema || 0}</div></div>
        <div class="rsm-item"><div class="rsm-lbl">En YAML</div><div class="rsm-val">${r.en_yaml || 0}</div></div>
        <div class="rsm-item"><div class="rsm-lbl">Profesores</div><div class="rsm-val">${r.professors || 0}</div></div>
        <div class="rsm-item"><div class="rsm-lbl">Estudiantes</div><div class="rsm-val">${r.students || 0}</div></div>
        <div class="rsm-item"><div class="rsm-lbl">Invitados</div><div class="rsm-val">${r.guests || 0}</div></div>
        <div class="rsm-item"><div class="rsm-lbl">Discrepancias</div>
            <div class="rsm-val ${r.discrepancias ? 'amb' : ''}">${r.discrepancias || 0}</div>
        </div>`;
}

function usrRender() {
    const tbody = document.getElementById('usr-tbody');
    if (!tbody) return;

    const filtroProblemas = document.getElementById('usr-f-solo-problemas')?.checked;
    const filtroActivos   = document.getElementById('usr-f-solo-activos')?.checked;
    const buscar = (document.getElementById('usr-f-buscar')?.value || '').toLowerCase();

    let users = _usrData.users || [];
    if (filtroProblemas) users = users.filter(u => u.estado !== 'ok');
    if (filtroActivos)   users = users.filter(u => u.active !== false);
    if (buscar)          users = users.filter(u =>
        (u.username || '').toLowerCase().includes(buscar) ||
        (u.fullname || '').toLowerCase().includes(buscar));

    if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty">Sin usuarios que mostrar</td></tr>';
        return;
    }

    tbody.innerHTML = users.map(u => {
        const estadoCls = {
            ok: 'estado-ok',
            pendiente_aplicar:  'estado-warn',
            pendiente_importar: 'estado-info',
        }[u.estado] || '';
        const estadoTxt = {
            ok: '✓ activo',
            pendiente_aplicar:  '↑ falta aplicar',
            pendiente_importar: '↓ importar',
        }[u.estado] || u.estado;

        const yamlTxt = u.en_yaml    ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--dim)">—</span>';
        const sisTxt  = u.en_sistema ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--dim)">—</span>';

        return `<tr data-username="${escapeHtml(u.username)}">
            <td style="font-family:var(--mono);"><b>${escapeHtml(u.username)}</b></td>
            <td>${escapeHtml(u.fullname || '—')}</td>
            <td style="font-family:var(--mono);">${u.uid || '—'}</td>
            <td><span class="hdr-badge">${escapeHtml(u.role || '?')}</span></td>
            <td><span class="task-badge ${estadoCls}" title="${escapeHtml(u.aviso || '')}">${estadoTxt}</span></td>
            <td style="font-family:var(--mono); text-align:center;">${yamlTxt} / ${sisTxt}</td>
            <td style="font-family:var(--mono); font-size:11.5px;">${escapeHtml(u.expires || '—')}</td>
            <td>
                <button class="btn btn-n" style="padding:4px 9px;font-size:11px;" onclick="usrEditar('${escapeHtml(u.username)}')">✏ Editar</button>
                ${window.ROL_ACTUAL === 'admin'
                    ? `<button class="btn btn-n" style="padding:4px 9px;font-size:11px;" onclick="usrPassword('${escapeHtml(u.username)}')">🔑 Pass</button>`
                    : ''}
                <button class="btn btn-r" style="padding:4px 9px;font-size:11px;" onclick="usrEliminar('${escapeHtml(u.username)}')">🗑</button>
            </td>
        </tr>`;
    }).join('');
}

function usrRefrescar() { usrCargar(false); toast('Actualizando…', 'info', 1000); }

// ─── Importar del sistema ────────────────────────────────────
// usrImportarDelSistema: eliminado (ahora auto-sync)

// ─── Aplicar al sistema ──────────────────────────────────────
// usrAplicarAlSistema: eliminado (PUT/crear aplican solos)

// ─── Nuevo (con password obligatoria) ────────────────────────
function usrNuevo() {
    const html = `
        <div class="modal-bg show" id="usr-modal" onclick="if(event.target===this)usrCerrarModal()">
            <div class="modal">
                <h3><span data-ico="plus"></span> Nuevo usuario</h3>
                <p style="font-size:12px;color:var(--dim);margin-bottom:14px;">
                    Se creará en el clúster (playbook) y podrá entrar al panel con esta contraseña.
                </p>
                <div class="form-group"><label>Usuario (login)</label>
                    <input type="text" id="usr-n-username" placeholder="ana.perez"></div>
                <div class="form-group"><label>Nombre completo</label>
                    <input type="text" id="usr-n-fullname" placeholder="Ana Pérez"></div>
                <div class="form-group"><label>Rol</label>
                    <select id="usr-n-role">
                        <option value="student">Estudiante (acceso panel: student)</option>
                        <option value="professor">Profesor (acceso panel: operator)</option>
                        <option value="guest">Invitado (acceso panel: viewer)</option>
                    </select></div>
                <div class="form-group"><label>UID (opcional — auto)</label>
                    <input type="number" id="usr-n-uid" placeholder="auto"></div>
                <div class="form-group"><label>Expiración (opcional)</label>
                    <input type="date" id="usr-n-expires"></div>
                <div class="form-group">
                    <label>Contraseña (mín. 8) <span style="color:var(--red)">*</span></label>
                    <input type="password" id="usr-n-password" placeholder="mín 8 caracteres">
                </div>
                <div class="modal-actions">
                    <button class="btn btn-n" onclick="usrCerrarModal()">Cancelar</button>
                    <button class="btn btn-g" onclick="usrCrearAhora()">Crear</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

function usrCerrarModal() { document.getElementById('usr-modal')?.remove(); }

async function usrCrearAhora() {
    const username = document.getElementById('usr-n-username').value.trim().toLowerCase();
    const fullname = document.getElementById('usr-n-fullname').value.trim();
    const role     = document.getElementById('usr-n-role').value;
    const uid      = document.getElementById('usr-n-uid').value.trim();
    const expires  = document.getElementById('usr-n-expires').value;
    const password = document.getElementById('usr-n-password').value;

    if (!username || !fullname) { toast('Usuario y nombre obligatorios', 'warning'); return; }
    if (password.length < 8)     { toast('Contraseña mínimo 8 caracteres', 'warning'); return; }

    toast('Creando usuario (playbook + contraseña)…', 'info', 8000);
    try {
        const data = await api('/api/usuarios', {
            method: 'POST',
            body: JSON.stringify({
                username, fullname, role,
                uid: uid ? parseInt(uid, 10) : null,
                expires: expires || null,
                password,
            }),
        });
        if (data.status !== 'success') {
            console.error(data.output);
            toast('Error: ' + (data.output || '').slice(0, 300), 'error', 8000);
            return;
        }
        toast('Usuario creado y contraseña aplicada', 'success');
        usrCerrarModal();
        usrCargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Editar ──────────────────────────────────────────────────
function usrEditar(username) {
    const u = (_usrData.users || []).find(x => x.username === username);
    if (!u) return;
    const html = `
        <div class="modal-bg show" id="usr-modal" onclick="if(event.target===this)usrCerrarModal()">
            <div class="modal">
                <h3><span data-ico="pencil"></span> Editar ${escapeHtml(username)}</h3>
                <div class="form-group"><label>Nombre completo</label>
                    <input type="text" id="usr-e-fullname" value="${escapeHtml(u.fullname || '')}"></div>
                <div class="form-group"><label>UID</label>
                    <input type="number" id="usr-e-uid" value="${u.uid || ''}"></div>
                <div class="form-group"><label>Rol</label>
                    <select id="usr-e-role">
                        ${['student','professor','guest'].map(r =>
                            `<option value="${r}" ${u.role === r ? 'selected' : ''}>${r}</option>`
                        ).join('')}
                    </select></div>
                <div class="form-group"><label>Expiración (vacío = sin expiración)</label>
                    <input type="date" id="usr-e-expires" value="${escapeHtml(u.expires || '')}"></div>
                <div class="form-group">
                    <label><input type="checkbox" id="usr-e-active" ${u.active !== false ? 'checked' : ''}> Activo</label>
                </div>
                <div class="modal-actions">
                    <button class="btn btn-n" onclick="usrCerrarModal()">Cancelar</button>
                    <button class="btn btn-g" onclick="usrGuardarEdicion('${escapeHtml(username)}')">Guardar</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

async function usrGuardarEdicion(username) {
    const cambios = {
        fullname: document.getElementById('usr-e-fullname').value.trim(),
        uid:      parseInt(document.getElementById('usr-e-uid').value, 10),
        role:     document.getElementById('usr-e-role').value,
        expires:  document.getElementById('usr-e-expires').value || null,
        active:   document.getElementById('usr-e-active').checked,
    };
    try {
        const data = await api(`/api/usuarios/${encodeURIComponent(username)}`, {
            method: 'PUT', body: JSON.stringify(cambios),
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || '').slice(0, 200), 'error', 6000);
            return;
        }
        toast(data.aplicado !== false
                ? 'Actualizado y aplicado al sistema'
                : 'Actualizado (falló aplicar — revisa log)',
              data.aplicado !== false ? 'success' : 'warning', 5000);
        usrCerrarModal();
        usrCargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Password ────────────────────────────────────────────────
async function usrPassword(username) {
    const nueva = prompt(`Nueva contraseña para ${username} (mín 8):`);
    if (!nueva) return;
    if (nueva.length < 8) { toast('Mínimo 8 caracteres', 'error'); return; }
    try {
        const data = await api(`/api/usuarios/${encodeURIComponent(username)}/password`, {
            method: 'POST', body: JSON.stringify({ password: nueva }),
        });
        toast(data.status === 'success' ? 'Contraseña actualizada' : `Error: ${data.output}`,
              data.status === 'success' ? 'success' : 'error');
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Eliminar ────────────────────────────────────────────────
async function usrEliminar(username) {
    if (!confirm(`¿Eliminar ${username}?\n\nSe borrará de: YAML + /etc/passwd + home del NAS + cuenta del panel.`)) return;
    toast('Eliminando…', 'info', 3000);
    try {
        const data = await api(`/api/usuarios/${encodeURIComponent(username)}`, { method: 'DELETE' });
        if (data.status === 'success') {
            toast(`${username} eliminado`, 'success', 4000);
            console.log(data.output);
        } else {
            toast('Error: ' + (data.output || '').slice(0, 200), 'error', 6000);
            console.error(data.output);
        }
        usrCargar();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Arranque ────────────────────────────────────────────────
// Init: solo si el rol cargado es admin (espera al evento 'rol-cargado')
function _initUsrV2() {
    if (window.ROL_ACTUAL !== 'admin') return;
    let primera = true;
    const tab = document.querySelector('.tab[data-tab="usuarios"]');
    if (tab) {
        tab.addEventListener('click', () => {
            usrCargar(primera);
            primera = false;
        });
    }
    if (tab?.classList.contains('activo')) usrCargar(true);
}

if (window._rolListo) {
    _initUsrV2();
} else {
    document.addEventListener('rol-cargado', _initUsrV2, { once: true });
    // Fallback por si /api/me tarda demasiado
    setTimeout(_initUsrV2, 2000);
}

window.usrRefrescar          = usrRefrescar;
window.usrNuevo              = usrNuevo;
window.usrCerrarModal        = usrCerrarModal;
window.usrCrearAhora         = usrCrearAhora;
window.usrEditar             = usrEditar;
window.usrGuardarEdicion     = usrGuardarEdicion;
window.usrPassword           = usrPassword;
window.usrEliminar           = usrEliminar;
window.usrCargar             = usrCargar;
window.usrRender             = usrRender;
