// ═══════════════════════════════════════════════════════════════
// Panel I2E — JavaScript principal
// ═══════════════════════════════════════════════════════════════

// ─── Auto-detección de IP ────────────────────────────────────
// Detecta automáticamente por qué host entró el usuario
// (10.4.8.10, 100.65.222.37, localhost, etc.) y construye URLs.
const PANEL_HOST = window.location.hostname;

function urlApp(port, proto = 'http') {
    return `${proto}://${PANEL_HOST}:${port}`;
}

// ─── CSRF token (desde meta tag) ─────────────────────────────
let CSRF_TOKEN = '';
document.addEventListener('DOMContentLoaded', () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) CSRF_TOKEN = meta.content;
});

// ─── Utilidades ──────────────────────────────────────────────
function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"]/g, c =>
        ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' })[c]);
}

function toast(msg, tipo = 'info', ms = 3500) {
    const c = document.getElementById('toasts');
    if (!c) return;
    const el = document.createElement('div');
    el.className = `toast ${tipo}`;
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 200);
    }, ms);
}

async function api(url, opts = {}) {
    const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    if (CSRF_TOKEN && opts.method && opts.method !== 'GET') {
        headers['X-CSRFToken'] = CSRF_TOKEN;
    }
    const res = await fetch(url, { ...opts, headers });
    if (res.status === 401) {
        toast('Sesión expirada', 'error');
        setTimeout(() => window.location = '/login', 1000);
        throw new Error('Unauthorized');
    }
    return res.json();
}

function $(id) { return document.getElementById(id); }

function claseBarra(pct) {
    if (pct >= 85) return 'barra-roja';
    if (pct >= 70) return 'barra-amarilla';
    return 'barra-verde';
}

// ─── Tema oscuro/claro ───────────────────────────────────────
const TEMA_KEY = 'panel-i2e-theme';

function aplicarTema(t) {
    document.documentElement.setAttribute('data-theme', t);
    // El icono del botón lo pinta ui.js
    localStorage.setItem(TEMA_KEY, t);
}

function toggleTema() {
    const actual = document.documentElement.getAttribute('data-theme') || 'light';
    aplicarTema(actual === 'dark' ? 'light' : 'dark');
}

// ─── Plegar secciones del sidebar ────────────────────────────
function plegar(cabecera) {
    const body = cabecera.nextElementSibling;
    if (!body) return;
    const oculto = body.classList.toggle('oculto');
    cabecera.classList.toggle('plegado', oculto);
}

// ─── Tabs del content area ───────────────────────────────────
function cambiarTab(tabId) {
    document.querySelectorAll('.tab').forEach(t =>
        t.classList.toggle('activo', t.dataset.tab === tabId));
    document.querySelectorAll('.tab-panel').forEach(p =>
        p.classList.toggle('activo', p.id === `tab-${tabId}`));
    // Cargar datos lazy al cambiar tab
    if (tabId === 'estado')       cargarNodos();
    if (tabId === 'apps')         cargarApps();
    if (tabId === 'usuarios')     cargarUsuarios();
    if (tabId === 'herramientas') cargarHerramientas();
    if (tabId === 'auditoria')    cargarAuditoria();
    if (tabId === 'playbooks')    cargarPlaybooks();
}

// ═══════════════════════════════════════════════════════════════
// MÓDULO: NODOS (estado + recursos)
// ═══════════════════════════════════════════════════════════════
let nodosCache = {};

async function cargarNodos() {
    const grid = $('nodos-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="empty"><span class="spin"></span> Consultando nodos…</div>';

    // 1) Traer el ESTADO (nodos online/offline) — es rápido, en paralelo
    let data;
    try {
        data = await api('/api/nodos/estado');
    } catch (e) {
        grid.innerHTML = '<div class="empty">Error al consultar nodos: ' + escapeHtml(e.message) + '</div>';
        return;
    }
    nodosCache = data.nodos || {};

    // 2) Pintar el grid INMEDIATAMENTE con los datos que ya tenemos
    grid.innerHTML = Object.entries(nodosCache).map(([ip, n]) => {
        const badges = (n.grupos || [])
            .filter(g => g !== 'compute' && g !== 'manager' && g !== 'nas')
            .map(g => `<span class="nodo-tag">${escapeHtml(g)}</span>`)
            .join('');
        return `
            <div class="nodo-card ${n.online ? '' : 'offline'}" id="nodo-${ip.replace(/\./g, '-')}" onclick="verDetalleNodo('${ip}')">
                <div class="nodo-head">
                    <div>
                        <div class="nodo-nombre">${escapeHtml(n.nombre)}</div>
                        <div class="nodo-ip">${ip} ${badges}</div>
                    </div>
                    <span class="nodo-estado ${n.online ? 'on' : 'off'}">${n.online ? '● ON' : '○ OFF'}</span>
                </div>
                <div class="metrica-mini"><div class="val" id="cpu-${ip.replace(/\./g, '-')}">—</div><div class="lbl">CPU</div></div>
                <div class="metrica-mini"><div class="val" id="ram-${ip.replace(/\./g, '-')}">—</div><div class="lbl">RAM</div></div>
                <div class="metrica-mini"><div class="val" id="disk-${ip.replace(/\./g, '-')}">—</div><div class="lbl">Disco</div></div>
            </div>`;
    }).join('');

    // 3) Recursos SOLO de nodos online, en paralelo y con timeout
    const online = Object.entries(nodosCache).filter(([_, n]) => n.online);
    if (!online.length) {
        grid.querySelectorAll('.nodo-card').forEach(c => c.classList.remove('checking'));
        return;
    }
    // Promise.allSettled: si uno falla, los demás siguen
    Promise.allSettled(online.map(([ip]) => cargarRecursos(ip)));
}

async function cargarRecursos(ip) {
    const id = ip.replace(/\./g, '-');
    try {
        const data = await api(`/api/nodos/${ip}/recursos`);
        if (data.status !== 'success') throw new Error(data.output || 'error');
        const r = data.recursos;

        const cpuEl = $(`cpu-${id}`);
        const ramEl = $(`ram-${id}`);
        const diskEl = $(`disk-${id}`);

        if (cpuEl)  cpuEl.innerHTML = `<span style="color:${r.cpu.usado_pct >= 85 ? 'var(--red)' : r.cpu.usado_pct >= 70 ? 'var(--amber)' : 'var(--text)'}">${r.cpu.usado_pct}%</span>`;
        if (ramEl)  ramEl.innerHTML = `<span style="color:${r.ram.usado_pct >= 85 ? 'var(--red)' : r.ram.usado_pct >= 70 ? 'var(--amber)' : 'var(--text)'}">${r.ram.usado_pct}%</span>`;
        if (diskEl) diskEl.innerHTML = `<span style="color:${r.disco.usado_pct >= 85 ? 'var(--red)' : r.disco.usado_pct >= 70 ? 'var(--amber)' : 'var(--text)'}">${r.disco.usado_pct}%</span>`;

        const card = $(`nodo-${id}`);
        if (card) card.classList.remove('checking');
    } catch (e) {
        console.warn(`Recursos de ${ip}: ${e.message}`);
    }
}

async function verDetalleNodo(ip) {
    const info = nodosCache[ip];
    if (!info) return;

    const html = `
        <div class="modal-bg show" id="modal-detalle" onclick="if(event.target===this)cerrarDetalle()">
            <div class="modal" style="max-width: 700px;">
                <h3>🖥️ ${escapeHtml(info.nombre)} <span style="font-family:var(--mono);font-size:12px;color:var(--dim);">${ip}</span></h3>
                <div id="detalle-body"><div class="empty"><span class="spin"></span> Cargando recursos…</div></div>
                <div class="modal-actions">
                    <button class="btn btn-b" onclick="abrirTerminal('${ip}')"><span data-ico="terminal"></span>Terminal</button>
                    <button class="btn btn-b" onclick="verHistoricoNodo('${ip}')"><span data-ico="chart"></span>Histórico</button>
                    <button class="btn btn-n" onclick="cerrarDetalle()">Cerrar</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);

    try {
        const data = await api(`/api/nodos/${ip}/recursos`);
        if (data.status === 'success') {
            const r = data.recursos;
            $('detalle-body').innerHTML = `
                <div class="sublabel">CPU</div>
                <div>${r.cpu.cores} núcleos · uso: <b>${r.cpu.usado_pct}%</b> · load: ${r.cpu.load.join(' / ')}</div>
                <div class="sublabel">RAM</div>
                <div>${r.ram.usado_mb} MB / ${r.ram.total_mb} MB (<b>${r.ram.usado_pct}%</b>)</div>
                <div class="sublabel">Disco</div>
                <div>${r.disco.usado} / ${r.disco.total} (<b>${r.disco.usado_pct}%</b>)</div>
            `;
        } else {
            $('detalle-body').innerHTML = `<div class="empty">${escapeHtml(data.output)}</div>`;
        }
    } catch (e) {
        $('detalle-body').innerHTML = `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function cerrarDetalle() {
    const m = $('modal-detalle');
    if (m) m.remove();
}

// ═══════════════════════════════════════════════════════════════
// MÓDULO: APLICACIONES — dinámico desde /api/apps
// ═══════════════════════════════════════════════════════════════
let _appsCache = [];

async function cargarApps() {
    const cont = $('apps-grid');
    if (!cont) return;
    cont.innerHTML = '<div class="empty"><span class="spin"></span> Verificando servicios…</div>';

    let data;
    try {
        data = await api('/api/apps');
    } catch (e) {
        cont.innerHTML = `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
        return;
    }
    if (data.status !== 'success') {
        cont.innerHTML = `<div class="empty">Error: ${escapeHtml(data.output || 'desconocido')}</div>`;
        return;
    }

    _appsCache = data.apps || [];

    if (!_appsCache.length) {
        cont.innerHTML = '<div class="empty">No hay aplicaciones configuradas. Pulsa ➕ Añadir app.</div>';
        return;
    }

    const esAdmin      = window.ROL_ACTUAL === 'admin';
    const puedeControl = ['operator', 'admin'].includes(window.ROL_ACTUAL);

    cont.innerHTML = _appsCache.map(a => {
        const activo = a.estado === 'activo';
        const url = a.url || urlApp(a.puerto, a.proto);
        const start_ok = a.start && a.start.valor && a.start.valor !== 'none';
        const stop_ok  = a.stop  && a.stop.valor  && a.stop.valor  !== 'none';

        return `
            <div class="app-card ${activo ? 'activo' : 'inactivo'}">
                <div class="app-header">
                    <span class="app-icon">${a.icono || '📦'}</span>
                    <span class="app-name">${escapeHtml(a.nombre)}</span>
                    <span class="app-estado ${activo ? 'activo' : 'inactivo'}">${a.estado}</span>
                    ${esAdmin ? `
                        <button class="btn btn-n app-btn-mini" onclick="appEditar('${a.id}')" title="Editar">⚙</button>
                        <button class="btn btn-r app-btn-mini" onclick="appEliminar('${a.id}')" title="Eliminar">🗑</button>
                    ` : ''}
                </div>
                <div style="font-size:11px;color:var(--dim);font-family:var(--mono);">${escapeHtml(url)}</div>
                ${a.descripcion ? `<div style="font-size:11.5px;color:var(--dim);margin-top:4px;">${escapeHtml(a.descripcion)}</div>` : ''}
                <div class="app-actions">
                    ${puedeControl && start_ok ? `<button class="btn btn-g" onclick="controlApp('${a.id}','start')">▶ Iniciar</button>` : ''}
                    ${puedeControl && stop_ok  ? `<button class="btn btn-r" onclick="controlApp('${a.id}','stop')">⏸ Detener</button>` : ''}
                    ${activo ? `<a class="app-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">↗ Abrir</a>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

async function controlApp(id, action) {
    const msg = action === 'start' ? `¿Iniciar ${id}?` : `¿Detener ${id}?`;
    if (!confirm(msg)) return;
    toast(`${action === 'start' ? 'Iniciando' : 'Deteniendo'} ${id}…`, 'info');
    try {
        const data = await api(`/api/apps/${encodeURIComponent(id)}/${action}`, { method: 'POST' });
        if (data.status === 'success') {
            toast(`${id} ${action === 'start' ? 'iniciado' : 'detenido'}`, 'success');
        } else {
            toast(`Error: ${(data.output || '').slice(0, 200)}`, 'error', 6000);
        }
        setTimeout(cargarApps, 2500);
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

// ─── Añadir / Editar app ────────────────────────────────────
function appNueva() { _appModal(null); }

function appEditar(id) {
    const app = _appsCache.find(a => a.id === id);
    if (!app) { toast('App no encontrada', 'error'); return; }
    _appModal(app);
}

function _appModal(app) {
    const esNueva = !app;
    const a = app || {
        id: '', nombre: '', icono: '📦', host: '10.4.8.10', puerto: 8080,
        proto: 'http', descripcion: '',
        check: { tipo: 'url', valor: '/' },
        start: null, stop: null, uninstall: null,
    };
    const start     = a.start     || { tipo: 'none', valor: '' };
    const stop      = a.stop      || { tipo: 'none', valor: '' };
    const uninstall = a.uninstall || { tipo: 'none', valor: '' };

    const html = `
        <div class="modal-bg show" id="app-modal" onclick="if(event.target===this)appCerrarModal()">
            <div class="modal" style="max-width:580px; max-height:88vh; overflow-y:auto;">
                <h3>${esNueva ? '➕ Nueva aplicación' : '⚙ Editar ' + escapeHtml(a.nombre)}</h3>

                <div class="form-group"><label>Nombre</label>
                    <input type="text" id="app-nombre" value="${escapeHtml(a.nombre)}" placeholder="Grafana"></div>

                <div style="display:grid; grid-template-columns:80px 1fr; gap:10px;">
                    <div class="form-group"><label>Icono</label>
                        <input type="text" id="app-icono" value="${escapeHtml(a.icono)}" maxlength="4"></div>
                    <div class="form-group"><label>Descripción</label>
                        <input type="text" id="app-descripcion" value="${escapeHtml(a.descripcion || '')}" placeholder="Opcional"></div>
                </div>

                <div style="display:grid; grid-template-columns:2fr 1fr 1fr; gap:10px;">
                    <div class="form-group"><label>Host</label>
                        <input type="text" id="app-host" value="${escapeHtml(a.host)}"></div>
                    <div class="form-group"><label>Puerto</label>
                        <input type="number" id="app-puerto" value="${a.puerto}" min="1" max="65535"></div>
                    <div class="form-group"><label>Proto</label>
                        <select id="app-proto">
                            <option value="http"  ${a.proto==='http'?'selected':''}>http</option>
                            <option value="https" ${a.proto==='https'?'selected':''}>https</option>
                        </select></div>
                </div>

                <div style="margin-top:14px; padding-top:10px; border-top:1px solid var(--border);">
                    <div style="font-size:11.5px; color:var(--dim); text-transform:uppercase; margin-bottom:8px;">Chequeo de estado</div>
                    <div style="display:grid; grid-template-columns:120px 1fr; gap:10px;">
                        <div class="form-group"><label>Tipo</label>
                            <select id="app-check-tipo">
                                <option value="url" ${a.check.tipo==='url'?'selected':''}>URL HTTP</option>
                                <option value="cmd" ${a.check.tipo==='cmd'?'selected':''}>Comando</option>
                            </select></div>
                        <div class="form-group"><label>Valor</label>
                            <input type="text" id="app-check-valor" value="${escapeHtml(a.check.valor)}" placeholder="/ o /api/health"></div>
                    </div>
                </div>

                <div style="margin-top:14px; padding-top:10px; border-top:1px solid var(--border);">
                    <div style="font-size:11.5px; color:var(--dim); text-transform:uppercase; margin-bottom:8px;">Iniciar (opcional)</div>
                    <div style="display:grid; grid-template-columns:120px 1fr; gap:10px;">
                        <div class="form-group"><label>Tipo</label>
                            <select id="app-start-tipo">
                                <option value="none"     ${start.tipo==='none'?'selected':''}>Ninguno</option>
                                <option value="playbook" ${start.tipo==='playbook'?'selected':''}>Playbook</option>
                                <option value="systemd"  ${start.tipo==='systemd'?'selected':''}>Systemd</option>
                            </select></div>
                        <div class="form-group"><label>Valor</label>
                            <input type="text" id="app-start-valor" value="${escapeHtml(start.valor)}" placeholder="19_spark_start.yml"></div>
                    </div>
                </div>

                <div style="margin-top:14px; padding-top:10px; border-top:1px solid var(--border);">
                    <div style="font-size:11.5px; color:var(--dim); text-transform:uppercase; margin-bottom:8px;">Detener (opcional)</div>
                    <div style="display:grid; grid-template-columns:120px 1fr; gap:10px;">
                        <div class="form-group"><label>Tipo</label>
                            <select id="app-stop-tipo">
                                <option value="none"     ${stop.tipo==='none'?'selected':''}>Ninguno</option>
                                <option value="playbook" ${stop.tipo==='playbook'?'selected':''}>Playbook</option>
                                <option value="systemd"  ${stop.tipo==='systemd'?'selected':''}>Systemd</option>
                            </select></div>
                        <div class="form-group"><label>Valor</label>
                            <input type="text" id="app-stop-valor" value="${escapeHtml(stop.valor)}" placeholder="19_spark_stop.yml"></div>
                    </div>
                </div>

                <div style="margin-top:14px; padding-top:10px; border-top:1px solid var(--border);">
                    <div style="font-size:11.5px; color:var(--dim); text-transform:uppercase; margin-bottom:8px;">Desinstalar (opcional)</div>
                    <div style="display:grid; grid-template-columns:120px 1fr; gap:10px;">
                        <div class="form-group"><label>Tipo</label>
                            <select id="app-uninstall-tipo">
                                <option value="none"     ${uninstall.tipo==='none'?'selected':''}>Ninguno</option>
                                <option value="playbook" ${uninstall.tipo==='playbook'?'selected':''}>Playbook</option>
                            </select></div>
                        <div class="form-group"><label>Valor</label>
                            <input type="text" id="app-uninstall-valor" value="${escapeHtml(uninstall.valor)}" placeholder="18_ray_uninstall.yml"></div>
                    </div>
                </div>

                <div class="modal-actions">
                    <button class="btn btn-n" onclick="appCerrarModal()">Cancelar</button>
                    <button class="btn btn-g" onclick="appGuardar(${esNueva ? 'null' : `'${a.id}'`})">${esNueva ? 'Añadir' : 'Guardar'}</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    setTimeout(() => $('app-nombre')?.focus(), 50);
}

function appCerrarModal() { document.getElementById('app-modal')?.remove(); }

function _leerAccion(pref) {
    const tipo  = document.getElementById(`app-${pref}-tipo`).value;
    const valor = document.getElementById(`app-${pref}-valor`).value.trim();
    if (tipo === 'none' || !valor) return null;
    return { tipo, valor };
}

async function appGuardar(id) {
    const nombre      = document.getElementById('app-nombre').value.trim();
    const icono       = document.getElementById('app-icono').value.trim() || '📦';
    const host        = document.getElementById('app-host').value.trim();
    const puerto      = parseInt(document.getElementById('app-puerto').value, 10);
    const proto       = document.getElementById('app-proto').value;
    const descripcion = document.getElementById('app-descripcion').value.trim();

    if (!nombre || !host || !puerto) {
        toast('Nombre, host y puerto son obligatorios', 'warning'); return;
    }

    const check_tipo  = document.getElementById('app-check-tipo').value;
    const check_valor = document.getElementById('app-check-valor').value.trim();
    if (!check_valor) { toast('El valor del chequeo es obligatorio', 'warning'); return; }

    let app_id = id;
    if (!app_id) {
        app_id = nombre.toLowerCase()
            .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
            .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        if (!/^[a-z]/.test(app_id)) app_id = 'a-' + app_id;
        if (!app_id) app_id = 'app';
    }

    const nueva = {
        id: app_id, nombre, icono, host, puerto, proto, descripcion,
        check: { tipo: check_tipo, valor: check_valor },
        start:     _leerAccion('start'),
        stop:      _leerAccion('stop'),
        uninstall: _leerAccion('uninstall'),
    };

    if (!id && _appsCache.some(a => a.id === app_id)) {
        toast(`Ya existe una app con id "${app_id}". Cambia el nombre.`, 'error');
        return;
    }

    const lista = id
        ? _appsCache.map(a => a.id === id ? nueva : a)
        : [..._appsCache, nueva];

    toast('Guardando…', 'info');
    try {
        const data = await api('/api/apps', {
            method: 'PUT',
            body: JSON.stringify({ apps: lista }),
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || '').slice(0, 200), 'error', 6000);
            return;
        }
        toast(id ? 'App actualizada' : 'App añadida', 'success');
        appCerrarModal();
        cargarApps();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function appEliminar(id) {
    const app = _appsCache.find(a => a.id === id);
    if (!app) return;
    const tiene_uninstall = !!(app.uninstall && app.uninstall.valor);
    let hacer_uninstall = false;

    if (tiene_uninstall) {
        if (!confirm(`¿Quitar "${app.nombre}" del panel?`)) return;
        hacer_uninstall = confirm(
            `¿Confirmas DESINSTALAR del clúster?\n\n` +
            `Se ejecutará: ${app.uninstall.valor}\n\n` +
            `OK = desinstalar y ocultar\n` +
            `Cancelar = SOLO ocultar del panel`
        );
    } else {
        if (!confirm(`¿Quitar "${app.nombre}" del panel?\n\n(No tiene playbook de desinstalación)`)) return;
    }

    toast(hacer_uninstall ? 'Desinstalando…' : 'Quitando…', 'info', 5000);
    try {
        const data = await api(`/api/apps/${encodeURIComponent(id)}`, {
            method: 'DELETE',
            body: JSON.stringify({ uninstall: hacer_uninstall }),
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || '').slice(0, 300), 'error', 8000);
            return;
        }
        toast('OK', 'success');
        cargarApps();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

window.appNueva       = appNueva;
window.appEditar      = appEditar;
window.appEliminar    = appEliminar;
window.appGuardar     = appGuardar;
window.appCerrarModal = appCerrarModal;


// ═══════════════════════════════════════════════════════════════
// MÓDULO: USUARIOS
// ═══════════════════════════════════════════════════════════════
async function cargarUsuarios() {
    const tbody = $('usuarios-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" class="empty">Cargando…</td></tr>';

    const data = await api('/api/usuarios');
    const usuarios = data.usuarios || [];

    if (usuarios.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty">No hay usuarios</td></tr>';
        return;
    }

    tbody.innerHTML = usuarios.map(u => `
        <tr>
            <td><b>${escapeHtml(u.fullname || u.username)}</b></td>
            <td style="font-family:var(--mono);">${escapeHtml(u.username)}</td>
            <td><span class="hdr-badge">${escapeHtml(u.role)}</span></td>
            <td style="font-family:var(--mono);">${u.uid}</td>
            <td>${u.expires ? escapeHtml(u.expires) : '—'}</td>
            <td>
                <button class="btn btn-n" onclick="modalPassword('${escapeHtml(u.username)}')" style="padding:4px 9px;font-size:11px;">🔑 Pass</button>
                <button class="btn btn-r" onclick="eliminarUsuario('${escapeHtml(u.username)}')" style="padding:4px 9px;font-size:11px;">🗑 Eliminar</button>
            </td>
        </tr>
    `).join('');
}

function modalNuevoUsuario() {
    const html = `
        <div class="modal-bg show" id="modal-user" onclick="if(event.target===this)cerrarModalUser()">
            <div class="modal">
                <h3>➕ Nuevo usuario</h3>
                <div class="form-group">
                    <label>Nombre completo</label>
                    <input type="text" id="u-fullname" placeholder="Ana Pérez">
                </div>
                <div class="form-group">
                    <label>Usuario (login)</label>
                    <input type="text" id="u-username" placeholder="ana.perez" pattern="[a-z][a-z0-9._-]{2,31}">
                </div>
                <div class="form-group">
                    <label>Rol</label>
                    <select id="u-role">
                        <option value="student">Estudiante</option>
                        <option value="professor">Profesor</option>
                        <option value="guest">Invitado</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Expiración (opcional)</label>
                    <input type="date" id="u-expires">
                </div>
                <div class="form-group">
                    <label>Contraseña inicial</label>
                    <input type="text" id="u-password" placeholder="Mínimo 8 caracteres">
                </div>
                <div class="modal-actions">
                    <button class="btn btn-n" onclick="cerrarModalUser()">Cancelar</button>
                    <button class="btn btn-g" onclick="crearUsuario()">Crear usuario</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

function cerrarModalUser() {
    const m = $('modal-user');
    if (m) m.remove();
}

async function crearUsuario() {
    const username = $('u-username').value.trim().toLowerCase();
    const fullname = $('u-fullname').value.trim();
    const role = $('u-role').value;
    const expires = $('u-expires').value;
    const password = $('u-password').value;

    if (!username || !fullname) {
        toast('Nombre completo y usuario requeridos', 'error');
        return;
    }
    if (password && password.length < 8) {
        toast('Contraseña mínimo 8 caracteres', 'error');
        return;
    }

    toast('Creando usuario…', 'info');
    try {
        const data = await api('/api/usuarios', {
            method: 'POST',
            body: JSON.stringify({ username, fullname, role, expires: expires || null })
        });
        if (data.status === 'success') {
            toast(`Usuario ${username} creado`, 'success');
            cerrarModalUser();
            cargarUsuarios();
            // Si se indicó password, aplicarlo
            if (password) {
                await api(`/api/usuarios/${username}/password`, {
                    method: 'POST',
                    body: JSON.stringify({ password })
                });
                toast('Contraseña aplicada', 'success');
            }
        } else {
            toast(`Error: ${data.output.slice(0, 200)}`, 'error');
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

function modalPassword(username) {
    const nueva = prompt(`Nueva contraseña para ${username} (mínimo 8 caracteres):`);
    if (!nueva) return;
    if (nueva.length < 8) {
        toast('Contraseña muy corta', 'error');
        return;
    }
    api(`/api/usuarios/${username}/password`, {
        method: 'POST',
        body: JSON.stringify({ password: nueva })
    }).then(d => {
        toast(d.status === 'success' ? 'Contraseña actualizada' : `Error: ${d.output}`, d.status === 'success' ? 'success' : 'error');
    });
}

async function eliminarUsuario(username) {
    if (!confirm(`¿Eliminar a ${username}? Se eliminará del clúster y del YAML.`)) return;
    toast(`Eliminando ${username}…`, 'info');
    try {
        const data = await api(`/api/usuarios/${username}`, { method: 'DELETE' });
        toast(data.status === 'success' ? 'Usuario eliminado' : `Error: ${data.output.slice(0, 200)}`,
              data.status === 'success' ? 'success' : 'error');
        cargarUsuarios();
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════
// MÓDULO: HERRAMIENTAS
// ═══════════════════════════════════════════════════════════════
async function cargarHerramientas() {
    const cont = $('herr-grid');
    if (!cont) return;

    const ip = $('herr-nodo')?.value || '10.4.8.10';
    cont.innerHTML = '<div class="empty"><span class="spin"></span> Verificando herramientas…</div>';

    try {
        const data = await api(`/api/nodos/${ip}/herramientas`);
        if (data.status !== 'success') {
            cont.innerHTML = `<div class="empty">Error: ${escapeHtml(data.output)}</div>`;
            return;
        }

        cont.innerHTML = Object.entries(data.nodos).map(([cat, tools]) => {
            const items = Object.entries(tools).map(([t, ok]) => `
                <div class="herr-item ${ok ? 'herr-ok' : 'herr-no'}">
                    <span>${ok ? '✓' : '✗'}</span>
                    <span>${escapeHtml(t)}</span>
                </div>
            `).join('');
            return `<div class="herr-cat"><h4>${escapeHtml(cat)}</h4>${items}</div>`;
        }).join('');
    } catch (e) {
        cont.innerHTML = `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════
// MÓDULO: AUDITORÍA
// ═══════════════════════════════════════════════════════════════
async function cargarAuditoria() {
    const tbody = $('audit-tbody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="5" class="empty">Cargando…</td></tr>';

    try {
        const data = await api('/api/audit?limit=200');
        const entries = data.entries || [];
        if (entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty">Sin eventos</td></tr>';
            return;
        }
        tbody.innerHTML = entries.map(e => `
            <tr>
                <td style="font-family:var(--mono);font-size:11.5px;">${escapeHtml(e.ts)}</td>
                <td><b>${escapeHtml(e.usuario)}</b></td>
                <td><code>${escapeHtml(e.accion)}</code></td>
                <td style="font-family:var(--mono);font-size:11.5px;">${escapeHtml(e.target || '—')}</td>
                <td>${e.exito ? '<span style="color:var(--green)">✓</span>' : '<span style="color:var(--red)">✗</span>'} ${escapeHtml(e.detalle || '')}</td>
            </tr>
        `).join('');
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" class="empty">Error: ${escapeHtml(e.message)}</td></tr>`;
    }
}

// ═══════════════════════════════════════════════════════════════
// MÓDULO: TERMINAL
// ═══════════════════════════════════════════════════════════════
let terminalNodo = null;

function abrirTerminal(ip) {
    cerrarDetalle();
    cambiarTab('terminal');
    terminalNodo = ip;
    const label = $('term-label');
    if (label) label.textContent = `root@${ip} ~ $`;
    const body = $('term-body');
    if (body) {
        body.innerHTML = `<span style="color:#6b9fc4;">[conectando a ${escapeHtml(ip)}…]</span>\n`;
    }
    const input = $('term-input');
    if (input) input.focus();
}

async function ejecutarEnTerminal() {
    const input = $('term-input');
    const body = $('term-body');
    if (!input || !body || !terminalNodo) return;

    const cmd = input.value.trim();
    if (!cmd) return;
    input.value = '';

    body.innerHTML += `<span style="color:#7ec699;">$ ${escapeHtml(cmd)}</span>\n`;
    body.scrollTop = body.scrollHeight;

    try {
        const data = await api('/api/ejecutar', {
            method: 'POST',
            body: JSON.stringify({
                accion: 'comando_libre',
                objetivo: terminalNodo,
                extra: cmd
            })
        });
        body.innerHTML += escapeHtml(data.output || '(sin salida)') + '\n\n';
    } catch (e) {
        body.innerHTML += `<span style="color:#e08080;">Error: ${escapeHtml(e.message)}</span>\n\n`;
    }
    body.scrollTop = body.scrollHeight;
}

function limpiarTerminal() {
    const body = $('term-body');
    if (body) body.innerHTML = '';
}

// ═══════════════════════════════════════════════════════════════
// MÓDULO: PLAYBOOKS
// ═══════════════════════════════════════════════════════════════
async function cargarPlaybooks() {
    const sel = $('pb-select');
    if (!sel) return;
    const prev = sel.value;
    try {
        const data = await api('/api/playbooks');
        const pbs = data.playbooks || [];
        sel.innerHTML = '<option value="">— Selecciona playbook —</option>' +
            pbs.map(p => {
                const nombre = p.nombre ?? p;
                const size   = p.size ? ` · ${p.size}b` : '';
                return `<option value="${escapeHtml(nombre)}">${escapeHtml(nombre)}${size}</option>`;
            }).join('');
        if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
    } catch (e) {
        console.error(e);
    }
}

// ejecutarPlaybook() ahora vive en tasks.js (Fase 3, background + polling)

// ═══════════════════════════════════════════════════════════════
// ARRANQUE
// ═══════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', async () => {
    // Tema guardado
    aplicarTema(localStorage.getItem(TEMA_KEY) || 'light');

    // Botón tema
    const btn = $('theme-btn');
    if (btn) btn.onclick = toggleTema;

    // El keydown de la terminal lo maneja terminal.js

    // Doble-click en el select de playbooks → abrir editor
    const selPb = $('pb-select');
    if (selPb) selPb.addEventListener('dblclick', () => editarPlaybookSeleccionado());

    // 1) Inventario primero (llena los <select>)
    try { await cargarInventario(); }
    catch (e) { console.warn('inventario:', e); }

    // 2) Vista inicial
    cargarNodos();
    cargarApps();

    // Auto-refresh estado cada 30s si estamos en el tab
    setInterval(() => {
        const t = document.querySelector('.tab[data-tab="estado"]');
        if (t && t.classList.contains('activo')) cargarNodos();
    }, 60000);

    console.log('[panel.js] arranque completo · host=' + PANEL_HOST);
});



// ─── Limpiar historial de tareas ───────────────────────────────
async function limpiarHistorialTareas() {
    if (!confirm("¿Eliminar todas las tareas terminadas del historial?")) return;
    try {
        const data = await api('/api/tasks/cleanup', { method: 'POST' });
        toast(data.output || 'Historial limpiado',
              data.status === 'success' ? 'success' : 'error');
        if (typeof cargarHistorialTareas === 'function') cargarHistorialTareas();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}
window.limpiarHistorialTareas = limpiarHistorialTareas;


// ═══════════════════════════════════════════════════════════════
// Visibilidad de tabs/páneles según rol (2026-10-03)
// ═══════════════════════════════════════════════════════════════
//
// Los tabs "Usuarios", "Playbooks", "Inventario" y "Auditoría"
// solo son para admin/operator. Los estudiantes NO los ven, aunque
// el bloque Jinja los renderice (porque también contiene Herramientas
// y Terminal que sí queremos mostrarles).
//
function _ajustarVisibilidadPorRol() {
    // Leer el rol desde el badge de la cabecera
    const badge = document.querySelector('.hdr-badge');
    const rol = (badge ? badge.textContent : '').trim().toLowerCase();

    // Solo aplicamos la restricción a estudiantes
    if (rol !== 'student' && rol !== 'viewer') return;

    // Tabs que NO deben ver los estudiantes/viewers
    const tabsRestringidos = ['usuarios', 'playbooks', 'inventario', 'auditoria'];

    for (const t of tabsRestringidos) {
        const tab = document.querySelector(`.tab[data-tab="${t}"]`);
        if (tab) tab.style.display = 'none';

        const panel = document.getElementById(`tab-${t}`);
        if (panel) panel.style.display = 'none';
    }

    // Si el tab "estado" no está activo por defecto, activarlo
    const tabActivo = document.querySelector('.tab.activo');
    if (!tabActivo) {
        const primero = document.querySelector('.tab:not([style*="display: none"])');
        if (primero) primero.click();
    }

    console.log('[rol] tabs ajustados para:', rol);
}

document.addEventListener('DOMContentLoaded', _ajustarVisibilidadPorRol);


// ═══════════════════════════════════════════════════════════════
// Ocultar el sidebar completo para estudiantes y viewers
// (contiene controles de Energía, Diagnóstico, Comando libre,
//  que NO deben estar disponibles para estudiantes)
// ═══════════════════════════════════════════════════════════════
function ocultarSidebarParaStudents() {
    const badge = document.querySelector('.hdr-badge');
    const rol = (badge ? badge.textContent : '').trim().toLowerCase();

    // Solo aplica a student y viewer
    if (rol !== 'student' && rol !== 'viewer') return;

    // Ocultar el sidebar completo
    const sidebar = document.querySelector('.sidebar');
    if (sidebar) {
        sidebar.style.display = 'none';
    }

    // Ocultar el botón de menú (hamburguesa) porque no hay sidebar
    const btnMenu = document.getElementById('hdr-menu');
    if (btnMenu) {
        btnMenu.style.display = 'none';
    }

    // Ajustar el layout: quitar la clase que añade el espacio del sidebar
    const layout = document.querySelector('.layout');
    if (layout) {
        layout.classList.add('no-sidebar');
    }

    console.log('[rol] sidebar oculto para:', rol);
}

document.addEventListener('DOMContentLoaded', ocultarSidebarParaStudents);

// ═══════════════════════════════════════════════════════════════
// Rol del usuario actual (para gating de UI en el cliente)
// El backend SIEMPRE revalida — esto es solo para ocultar botones
// ═══════════════════════════════════════════════════════════════
window.ROL_ACTUAL = 'viewer';      // default seguro
window.USUARIO_ACTUAL = '';
window._rolListo = false;

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const res = await fetch('/api/me', { credentials: 'same-origin' });
        if (res.ok) {
            const me = await res.json();
            window.ROL_ACTUAL     = me.role || 'viewer';
            window.USUARIO_ACTUAL = me.usuario || '';
            window._rolListo      = true;
            console.log('[panel] rol cargado:', me);
            document.dispatchEvent(new CustomEvent('rol-cargado', { detail: me }));
        }
    } catch (e) {
        console.warn('[panel] no pude cargar /api/me:', e);
    }
});

// ═══════════════════════════════════════════════════════════════
// MÓDULO: HERRAMIENTAS — edición desde el panel (solo admin)
// ═══════════════════════════════════════════════════════════════
let _herrCache = { categorias: [] };

async function herrEditar() {
    let data;
    try {
        data = await api('/api/herramientas');
    } catch (e) { toast('Error: ' + e.message, 'error'); return; }
    if (data.status !== 'success') { toast('Error cargando herramientas', 'error'); return; }

    _herrCache = { categorias: JSON.parse(JSON.stringify(data.categorias || [])) };
    _herrRenderModal();
}

function _herrRenderModal() {
    document.getElementById('herr-modal')?.remove();

    const cats = _herrCache.categorias;
    const body = cats.map((c, ci) => `
        <div class="herr-cat-edit">
            <div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
                <input type="text" value="${escapeHtml(c.nombre)}"
                       oninput="_herrSetNombre(${ci}, this.value)"
                       style="flex:1; font-weight:600;" placeholder="Nombre categoría">
                <button class="btn btn-n app-btn-mini" onclick="_herrMoverCat(${ci}, -1)" title="Subir">↑</button>
                <button class="btn btn-n app-btn-mini" onclick="_herrMoverCat(${ci}, 1)"  title="Bajar">↓</button>
                <button class="btn btn-r app-btn-mini" onclick="_herrBorrarCat(${ci})" title="Eliminar categoría">🗑</button>
            </div>
            <div style="margin-left:16px;">
                ${c.herramientas.map((h, hi) => `
                    <div style="display:flex; align-items:center; gap:6px; margin-bottom:4px;">
                        <input type="text" value="${escapeHtml(h)}"
                               oninput="_herrSetHerramienta(${ci}, ${hi}, this.value)"
                               style="flex:1; font-family:var(--mono);" placeholder="nombre-comando">
                        <button class="btn btn-n app-btn-mini" onclick="_herrMoverHerr(${ci}, ${hi}, -1)">↑</button>
                        <button class="btn btn-n app-btn-mini" onclick="_herrMoverHerr(${ci}, ${hi}, 1)">↓</button>
                        <button class="btn btn-r app-btn-mini" onclick="_herrBorrarHerr(${ci}, ${hi})">🗑</button>
                    </div>
                `).join('')}
                <button class="btn btn-n app-btn-mini" onclick="_herrAddHerr(${ci})" style="margin-top:2px;">+ herramienta</button>
            </div>
        </div>
    `).join('');

    const html = `
        <div class="modal-bg show" id="herr-modal" onclick="if(event.target===this)herrCerrarModal()">
            <div class="modal" style="max-width:620px; max-height:88vh; overflow-y:auto;">
                <h3>⚙ Editar herramientas</h3>
                <p style="font-size:12px;color:var(--dim);margin-bottom:14px;">
                    Comandos que se verifican con <code>command -v</code> en cada nodo.
                    Solo diagnóstico — no instala nada.
                </p>
                <div id="herr-modal-body">${body || '<div class="empty">Sin categorías. Pulsa + categoría.</div>'}</div>
                <button class="btn btn-n" onclick="_herrAddCat()" style="margin-top:12px;">+ categoría</button>
                <div class="modal-actions">
                    <button class="btn btn-n" onclick="herrCerrarModal()">Cancelar</button>
                    <button class="btn btn-g" onclick="herrGuardar()">Guardar</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

function _herrSetNombre(ci, v) { _herrCache.categorias[ci].nombre = v; }
function _herrSetHerramienta(ci, hi, v) { _herrCache.categorias[ci].herramientas[hi] = v; }

function _herrMoverCat(ci, delta) {
    const cats = _herrCache.categorias;
    const ni = ci + delta;
    if (ni < 0 || ni >= cats.length) return;
    [cats[ci], cats[ni]] = [cats[ni], cats[ci]];
    _herrRenderModal();
}

function _herrMoverHerr(ci, hi, delta) {
    const hs = _herrCache.categorias[ci].herramientas;
    const ni = hi + delta;
    if (ni < 0 || ni >= hs.length) return;
    [hs[hi], hs[ni]] = [hs[ni], hs[hi]];
    _herrRenderModal();
}

function _herrBorrarCat(ci) {
    if (!confirm(`¿Eliminar categoría "${_herrCache.categorias[ci].nombre}"?`)) return;
    _herrCache.categorias.splice(ci, 1);
    _herrRenderModal();
}

function _herrBorrarHerr(ci, hi) {
    _herrCache.categorias[ci].herramientas.splice(hi, 1);
    _herrRenderModal();
}

function _herrAddHerr(ci) {
    _herrCache.categorias[ci].herramientas.push('');
    _herrRenderModal();
    setTimeout(() => {
        const inputs = document.querySelectorAll('#herr-modal-body input');
        inputs[inputs.length - 1]?.focus();
    }, 30);
}

function _herrAddCat() {
    _herrCache.categorias.push({ nombre: 'Nueva categoría', herramientas: [] });
    _herrRenderModal();
}

function herrCerrarModal() { document.getElementById('herr-modal')?.remove(); }

async function herrGuardar() {
    const limpio = _herrCache.categorias
        .map(c => ({
            nombre: (c.nombre || '').trim(),
            herramientas: (c.herramientas || []).map(h => (h || '').trim()).filter(Boolean),
        }))
        .filter(c => c.nombre);

    const nombres = limpio.map(c => c.nombre);
    if (new Set(nombres).size !== nombres.length) {
        toast('Hay categorías con nombre duplicado', 'error', 5000);
        return;
    }

    toast('Guardando…', 'info');
    try {
        const data = await api('/api/herramientas', {
            method: 'PUT',
            body: JSON.stringify({ categorias: limpio }),
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || '').slice(0, 200), 'error', 6000);
            return;
        }
        toast('Herramientas guardadas', 'success');
        herrCerrarModal();
        cargarHerramientas();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

window.herrEditar          = herrEditar;
window.herrCerrarModal     = herrCerrarModal;
window.herrGuardar         = herrGuardar;
window._herrSetNombre      = _herrSetNombre;
window._herrSetHerramienta = _herrSetHerramienta;
window._herrMoverCat       = _herrMoverCat;
window._herrMoverHerr      = _herrMoverHerr;
window._herrBorrarCat      = _herrBorrarCat;
window._herrBorrarHerr     = _herrBorrarHerr;
window._herrAddHerr        = _herrAddHerr;
window._herrAddCat         = _herrAddCat;
