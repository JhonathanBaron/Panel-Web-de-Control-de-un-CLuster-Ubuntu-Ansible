// ═══════════════════════════════════════════════════════════════
// Tareas en background — playbooks con progreso en vivo
// ═══════════════════════════════════════════════════════════════

const _TASK_LS_KEY = 'panel-i2e-last-task';
let _pollTaskId = null;
let _pollTimer  = null;
let _pollSince  = 0;
let _pollActivo = null;

// ─── Colorear líneas de Ansible ──────────────────────────────
function _claseLineaAnsible(txt) {
    const t = txt;
    if (/^PLAY\s+\[/.test(t) || /^PLAY RECAP/.test(t))            return 'pb-play';
    if (/^TASK\s+\[/.test(t) || /^RUNNING HANDLER/.test(t))        return 'pb-task';
    if (/^\s*ok:\s/.test(t))                                       return 'pb-ok';
    if (/^\s*changed:\s/.test(t))                                  return 'pb-changed';
    if (/^\s*(fatal|failed):\s/.test(t))                           return 'pb-fail';
    if (/^\s*skipping:\s/.test(t))                                 return 'pb-skip';
    if (/^\s*included:\s/.test(t))                                 return 'pb-included';
    return 'pb-line';
}

// ─── Ejecutar playbook ───────────────────────────────────────
async function ejecutarPlaybook() {
    const sel = document.getElementById('pb-select');
    if (!sel) return;
    const nombre = sel.value;
    if (!nombre) { toast('Selecciona un playbook', 'warning'); return; }

    try {
        const data = await api('/api/playbooks/ejecutar', {
            method: 'POST',
            body: JSON.stringify({ nombre })
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error');
            return;
        }
        localStorage.setItem(_TASK_LS_KEY, data.task_id);
        toast(`Playbook lanzado en background`, 'success');
        _iniciarPolling(data.task_id);
        setTimeout(cargarHistorialTareas, 500);
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ─── Polling ─────────────────────────────────────────────────
function _iniciarPolling(taskId) {
    if (_pollTimer) clearInterval(_pollTimer);
    _pollTaskId = taskId;
    _pollSince  = 0;

    const out = document.getElementById('pb-output');
    const prg = document.getElementById('pb-progress');
    if (out) { out.classList.remove('oculto'); out.innerHTML = ''; }
    if (prg) { prg.classList.remove('oculto', 'done', 'err');
               prg.querySelector('div').style.width = '0%'; }

    _pollTaskOnce();               // primera llamada inmediata
    _pollTimer = setInterval(_pollTaskOnce, 1500);
}

async function _pollTaskOnce() {
    if (!_pollTaskId) return;
    let data;
    try {
        data = await api(`/api/tasks/${_pollTaskId}?since=${_pollSince}`);
    } catch (e) {
        console.warn('poll error', e);
        return;
    }
    const t = data.task;
    if (!t) return;

    const out = document.getElementById('pb-output');
    if (out && t.lines && t.lines.length) {
        const html = t.lines.map(l => {
            const cls = _claseLineaAnsible(l.txt);
            return `<div class="${cls}">${escapeHtml(l.txt) || '&nbsp;'}</div>`;
        }).join('');
        out.insertAdjacentHTML('beforeend', html);
        out.scrollTop = out.scrollHeight;
        _pollSince += t.lines.length;
    }

    // Estado
    if (t.status !== 'running') {
        clearInterval(_pollTimer);
        _pollTimer = null;

        const prg = document.getElementById('pb-progress');
        if (prg) {
            prg.classList.add('done');
            if (t.status === 'error' || t.status === 'timeout')
                prg.classList.replace('done', 'err');
            prg.querySelector('div').style.width = '100%';
        }

        const msg = {
            ok:      '✓ Playbook completado',
            error:   '✗ Playbook con errores',
            timeout: '⏱ Playbook abortado por timeout',
        }[t.status] || t.status;

        toast(msg, t.status === 'ok' ? 'success' : 'error');
        cargarHistorialTareas();
        _actualizarBadgeTareas();
    } else {
        _actualizarBadgeTareas();
    }
}

// ─── Historial de tareas ─────────────────────────────────────
async function cargarHistorialTareas() {
    const cont = document.getElementById('pb-historial');
    if (!cont) return;

    try {
        const data = await api('/api/tasks?limit=20');
        const ts = data.tasks || [];
        if (!ts.length) {
            cont.innerHTML = '<div class="empty" style="padding:16px;">Sin ejecuciones registradas</div>';
            return;
        }
        cont.innerHTML = `
            <table class="tabla" style="font-size:12px;">
                <thead>
                    <tr>
                        <th style="width:150px;">Inicio</th>
                        <th style="width:140px;">Usuario</th>
                        <th>Playbook</th>
                        <th style="width:100px;">Estado</th>
                        <th style="width:80px;"></th>
                    </tr>
                </thead>
                <tbody>
                    ${ts.map(t => {
                        const cls = {
                            running:'hdr-badge', ok:'estado-ok',
                            error:'estado-err', timeout:'estado-warn'
                        }[t.status] || '';
                        const icono = {
                            running:'●', ok:'✓', error:'✗', timeout:'⏱'
                        }[t.status] || '?';
                        return `<tr>
                            <td style="font-family:var(--mono);font-size:11px;">${escapeHtml(t.started)}</td>
                            <td>${escapeHtml(t.usuario || '—')}</td>
                            <td style="font-family:var(--mono);font-size:11.5px;">${escapeHtml(t.nombre || t.kind)}</td>
                            <td><span class="task-badge ${cls}">${icono} ${t.status}</span></td>
                            <td><button class="btn btn-n" style="padding:3px 9px;font-size:11px;"
                                       onclick="verTarea('${t.id}')">Ver</button></td>
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>`;
    } catch (e) {
        cont.innerHTML = `<div class="empty" style="padding:16px;">Error: ${escapeHtml(e.message)}</div>`;
    }
}

async function verTarea(taskId) {
    const out = document.getElementById('pb-output');
    const prg = document.getElementById('pb-progress');
    if (!out) return;
    out.classList.remove('oculto');
    out.innerHTML = '<span class="term-dim">Cargando salida…</span>';
    if (prg) prg.classList.add('oculto');

    try {
        const data = await api(`/api/tasks/${taskId}`);
        const t = data.task;
        out.innerHTML = (t.lines || []).map(l => {
            const cls = _claseLineaAnsible(l.txt);
            return `<div class="${cls}">${escapeHtml(l.txt) || '&nbsp;'}</div>`;
        }).join('');
        out.scrollTop = out.scrollHeight;

        // Si está corriendo, seguimos polling
        if (t.status === 'running') {
            _iniciarPolling(taskId);
            _pollSince = (t.lines || []).length;
        }
    } catch (e) {
        out.innerHTML = `<span class="term-err">Error: ${escapeHtml(e.message)}</span>`;
    }
}

// ─── Badge en header con tareas corriendo ────────────────────
async function _actualizarBadgeTareas() {
    const el = document.getElementById('hdr-tareas');
    if (!el) return;
    try {
        const data = await api('/api/tasks?limit=50');
        const corriendo = (data.tasks || []).filter(t => t.status === 'running');
        if (corriendo.length === 0) {
            el.classList.add('oculto');
            el.textContent = '';
        } else {
            el.classList.remove('oculto');
            el.innerHTML = `<span data-ico="refresh"></span>${corriendo.length} tarea${corriendo.length === 1 ? '' : 's'}`;
            el.title = corriendo.map(t => t.nombre || t.kind).join(', ');
        }
    } catch {}
}

// ─── Arranque ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // ¿Hay una tarea corriendo de la última visita?
    const last = localStorage.getItem(_TASK_LS_KEY);
    if (last) {
        api(`/api/tasks/${last}`).then(d => {
            if (d.task && d.task.status === 'running') {
                toast('Retomando tarea en curso…', 'info');
                _iniciarPolling(last);
            }
        }).catch(() => {});
    }
    _actualizarBadgeTareas();
    setInterval(_actualizarBadgeTareas, 10000);

    const tabPb = document.querySelector('.tab[data-tab="playbooks"]');
    if (tabPb) tabPb.addEventListener('click', cargarHistorialTareas);
});

window.ejecutarPlaybook   = ejecutarPlaybook;
window.verTarea           = verTarea;
window.cargarHistorialTareas = cargarHistorialTareas;
