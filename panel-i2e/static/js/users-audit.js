// ═══════════════════════════════════════════════════════════════
// Auditoría de usuarios — huérfanos, conflictos, espacio
// ═══════════════════════════════════════════════════════════════

async function usrAuditRefrescar() {
    const cont = document.getElementById('usr-audit-list');
    if (!cont) return;
    cont.innerHTML = '<div class="empty"><span class="spin"></span> Analizando las 4 fuentes…</div>';

    try {
        const data = await api('/api/usuarios/audit');
        if (data.status !== 'success') {
            cont.innerHTML = `<div class="empty">Error: ${escapeHtml(data.output)}</div>`;
            return;
        }

        usrAuditRender(data);
    } catch (e) {
        cont.innerHTML = `<div class="empty">Error: ${escapeHtml(e.message)}</div>`;
    }
}

function _fmtBytes(n) {
    if (!n || n < 1024) return (n || 0) + ' B';
    const u = ['KB','MB','GB','TB'];
    let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
    return n.toFixed(n >= 10 ? 0 : 1) + ' ' + u[i];
}

function _badgeEstado(estado) {
    const map = {
        'ok':                   ['#1a7f37', '✓ OK'],
        'huerfano':             ['#c1272d', '⚠ HUÉRFANO'],
        'sin_home':             ['#b45309', '⚠ SIN HOME'],
        'pendiente_aplicar':    ['#8250df', '· Sin aplicar'],
        'pendiente_importar':   ['#0e7490', '· Sin importar'],
        'parcial':              ['#6b7280', '· Parcial'],
    };
    const [color, txt] = map[estado] || ['#6b7280', estado];
    return `<span style="color:${color}; font-weight:600; font-size:11px;">${txt}</span>`;
}

function usrAuditRender(data) {
    const cont = document.getElementById('usr-audit-list');
    if (!cont) return;

    const res = data.resumen || {};
    const usuarios = data.usuarios || [];
    const conflictos = data.conflictos_uid || {};

    // ─── Resumen ────────────────────────────────────────────
    let html = `
        <div class="usr-audit-resumen">
            <div class="usr-audit-stat">
                <div class="val">${res.total || 0}</div>
                <div class="lbl">Total</div>
            </div>
            <div class="usr-audit-stat ok">
                <div class="val">${res.ok || 0}</div>
                <div class="lbl">OK</div>
            </div>
            <div class="usr-audit-stat warn">
                <div class="val">${res.huerfanos || 0}</div>
                <div class="lbl">Huérfanos</div>
            </div>
            <div class="usr-audit-stat warn">
                <div class="val">${res.sin_home || 0}</div>
                <div class="lbl">Sin home</div>
            </div>
            <div class="usr-audit-stat warn">
                <div class="val">${res.conflictos_uid || 0}</div>
                <div class="lbl">Conflictos UID</div>
            </div>
        </div>
    `;

    // ─── Tabla ──────────────────────────────────────────────
    if (usuarios.length === 0) {
        html += '<div class="empty">No hay usuarios</div>';
    } else {
        html += `
        <table class="tabla usr-audit-tabla">
            <thead>
                <tr>
                    <th>Usuario</th>
                    <th>UID</th>
                    <th>Espacio</th>
                    <th>YAML</th>
                    <th>Panel</th>
                    <th>Linux</th>
                    <th>NAS</th>
                    <th>Estado</th>
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
        `;

        for (const u of usuarios) {
            const ck = v => v
                ? '<span style="color:#1a7f37;">✓</span>'
                : '<span style="color:#c1272d;">✗</span>';

            const conflicto = u.tiene_conflicto_uid
                ? ` <span title="Comparte UID con: ${u.conflicto_con.join(', ')}"
                          style="color:#c1272d; font-weight:bold;">⚠</span>`
                : '';

            // El backend decide si se puede purgar
            const botonPurgar = u.puede_purgar
                ? `<button class="btn btn-r" style="padding:3px 8px; font-size:11px;"
                           onclick="usrAuditPurgar('${escapeHtml(u.username)}')"
                           title="Solo para huérfanos (carpeta sin usuario)">
                       🗑 Purgar
                   </button>`
                : '';

            // El backend decide si se puede reparar
            const botonReparar = u.puede_reparar
                ? `<button class="btn btn-g" style="padding:3px 8px; font-size:11px;"
                           onclick="usrAuditReparar('${escapeHtml(u.username)}')"
                           title="Recrear el home faltante">
                       🔧 Reparar
                   </button>`
                : '';

            html += `
                <tr class="${u.estado === 'huerfano' ? 'fila-huerfano' : ''}">
                    <td><b>${escapeHtml(u.username)}</b>${conflicto}</td>
                    <td style="font-family:var(--mono);">${u.uid || '—'}</td>
                    <td style="font-family:var(--mono);">${u.size_bytes ? _fmtBytes(u.size_bytes) : '—'}</td>
                    <td>${ck(u.en_yaml)}</td>
                    <td>${ck(u.en_panel)}</td>
                    <td>${ck(u.en_linux)}</td>
                    <td>${ck(u.en_nas)}</td>
                    <td>${_badgeEstado(u.estado)}</td>
                    <td>
                        ${botonReparar}
                        ${botonPurgar}
                    </td>
                </tr>
            `;
        }
        html += '</tbody></table>';
    }

    // ─── Conflictos de UID ──────────────────────────────────
    if (Object.keys(conflictos).length > 0) {
        html += `
            <div class="usr-audit-conflicto">
                <b style="color:#c1272d;">⚠ Conflictos de UID detectados:</b>
                <ul>
        `;
        for (const [uid, users] of Object.entries(conflictos)) {
            html += `<li>UID <code>${uid}</code>: ${users.map(escapeHtml).join(', ')}</li>`;
        }
        html += '</ul></div>';
    }

    cont.innerHTML = html;
}

async function usrAuditPurgar(username) {
    if (!username) return;

    // Confirmación doble (es destructivo)
    if (!confirm(`¿Purgar el usuario "${username}"?\n\n` +
                 `Se eliminará de:\n` +
                 `  · users.yaml\n` +
                 `  · /etc/passwd (todos los nodos)\n` +
                 `  · Credenciales del panel\n` +
                 `  · Cuota\n` +
                 `  · Carpeta del NAS (se mueve a papelera)`)) {
        return;
    }

    if (!confirm(`Confirma UNA VEZ MÁS:\n\n` +
                 `Purgar "${username}" de todas las fuentes.`)) {
        return;
    }

    toast(`Purgando ${username}…`, 'info');

    try {
        const data = await api(`/api/usuarios/${username}/purgar`, {
            method: 'POST',
            body: JSON.stringify({ modo: 'papelera' }),
        });

        if (data.status === 'success') {
            toast(`${username} purgado`, 'success');
            // Mostrar detalles en un modal
            _usrAuditMostrarResultado(username, data.output);
        } else {
            toast(`Error: ${(data.output || '').slice(0, 200)}`, 'error');
        }

        setTimeout(usrAuditRefrescar, 1000);
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

function _usrAuditMostrarResultado(username, output) {
    const html = `
        <div class="modal-bg show" id="modal-purgar-result" onclick="if(event.target===this)this.remove()">
            <div class="modal" style="max-width:600px;">
                <h3>✅ ${escapeHtml(username)} purgado</h3>
                <pre style="white-space:pre-wrap; font-size:12px; line-height:1.5;
                            background:var(--bg2); padding:12px; border-radius:6px;
                            max-height:400px; overflow:auto;">${escapeHtml(output)}</pre>
                <div class="modal-actions">
                    <button class="btn btn-b" onclick="document.getElementById('modal-purgar-result').remove()">Cerrar</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
}

async function usrAuditReparar(username) {
    if (!confirm(`¿Recrear el home de "${username}" en el NAS?`)) return;
    toast('Función de reparación pendiente', 'warning');
}

window.usrAuditRefrescar = usrAuditRefrescar;
window.usrAuditPurgar = usrAuditPurgar;
window.usrAuditReparar = usrAuditReparar;

// Cargar al abrir la pestaña
document.addEventListener('DOMContentLoaded', () => {
    const tabBtn = document.querySelector('.tab[data-tab="usuarios"]');
    if (tabBtn) {
        tabBtn.addEventListener('click', () => {
            setTimeout(usrAuditRefrescar, 300);
        });
    }
});
