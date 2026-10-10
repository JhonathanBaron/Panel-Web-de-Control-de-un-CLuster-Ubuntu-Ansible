// ═══════════════════════════════════════════════════════════════
// Panel I2E — UI helpers v2
// ═══════════════════════════════════════════════════════════════

// ─── Tema con iconos SVG ─────────────────────────────────────
const _TEMA_KEY_UI = 'panel-i2e-theme';

function _aplicarTemaV2(t) {
    document.documentElement.setAttribute('data-theme', t);
    const btn = document.getElementById('theme-btn');
    if (btn) {
        btn.innerHTML = `<span data-ico="${t === 'dark' ? 'sun' : 'moon'}"></span>`;
        btn.title = t === 'dark' ? 'Modo claro' : 'Modo oscuro';
    }
    localStorage.setItem(_TEMA_KEY_UI, t);
}
window.aplicarTema = _aplicarTemaV2;
window.toggleTema = function () {
    const actual = document.documentElement.getAttribute('data-theme') || 'light';
    _aplicarTemaV2(actual === 'dark' ? 'light' : 'dark');
};

// ─── Hamburger sidebar ───────────────────────────────────────
function _initHamburger() {
    const btn = document.getElementById('hdr-menu');
    const sb  = document.querySelector('.sidebar');
    const bd  = document.getElementById('sidebar-backdrop');
    if (!btn || !sb) return;

    const cerrar = () => { sb.classList.remove('open'); bd?.classList.remove('show'); };
    const abrir  = () => { sb.classList.add('open');    bd?.classList.add('show'); };

    btn.addEventListener('click', () => sb.classList.contains('open') ? cerrar() : abrir());
    bd?.addEventListener('click', cerrar);
    // Cierra al pulsar cualquier opción del sidebar en móvil
    sb.addEventListener('click', e => {
        if (window.innerWidth <= 900 && e.target.closest('.btn, select, .tab')) {
            setTimeout(cerrar, 150);
        }
    });
}

// ─── Barra resumen del clúster ───────────────────────────────
async function cargarResumenCluster() {
    const cont = document.getElementById('cluster-resumen');
    if (!cont) return;

    cont.innerHTML = `<div class="rsm-item"><div class="rsm-lbl">Cargando…</div><div class="rsm-val amb"><span class="spin"></span></div></div>`;

    try {
        const inv = await api('/api/inventory');
        const estado = await api('/api/nodos/estado');

        const hosts = inv.hosts || [];
        const nodos = estado.nodos || {};

        const total   = hosts.length;
        const online  = Object.values(nodos).filter(n => n.online).length;
        const offline = total - online;

        const heavy   = hosts.filter(h => (h.grupos || []).includes('heavy')).length;
        const light   = hosts.filter(h => (h.grupos || []).includes('light')).length;
        const workers = hosts.filter(h => h.rol === 'worker').length;

        cont.innerHTML = `
            <div class="rsm-item">
                <div class="rsm-lbl">Total nodos</div>
                <div class="rsm-val">${total}</div>
            </div>
            <div class="rsm-item">
                <div class="rsm-lbl">En línea</div>
                <div class="rsm-val on">${online}</div>
            </div>
            <div class="rsm-item">
                <div class="rsm-lbl">Fuera de línea</div>
                <div class="rsm-val ${offline > 0 ? 'off' : ''}">${offline}</div>
            </div>
            <div class="rsm-item">
                <div class="rsm-lbl">Workers</div>
                <div class="rsm-val">${workers}</div>
            </div>
            <div class="rsm-item">
                <div class="rsm-lbl">Heavy / Light</div>
                <div class="rsm-val">${heavy} / ${light}</div>
            </div>`;
    } catch (e) {
        cont.innerHTML = `<div class="rsm-item"><div class="rsm-lbl">Error</div><div class="rsm-val off">${escapeHtml(e.message)}</div></div>`;
    }
}

// ─── Arranque ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    _initHamburger();
    // El tema ya se aplicó en panel.js; solo pintamos icono correcto
    _aplicarTemaV2(localStorage.getItem(_TEMA_KEY_UI) || 'light');

    // Resumen del clúster cuando estamos en la tab Estado
    const tabEstado = document.querySelector('.tab[data-tab="estado"]');
    if (tabEstado) {
        tabEstado.addEventListener('click', cargarResumenCluster);
    }
    if (tabEstado?.classList.contains('activo')) {
        setTimeout(cargarResumenCluster, 400);
    }

    // Auto-refresh del resumen cada 60s si seguimos en Estado
    setInterval(() => {
        const t = document.querySelector('.tab[data-tab="estado"]');
        if (t && t.classList.contains('activo') &&
            document.getElementById('cluster-resumen')?.innerHTML.trim()) {
            cargarResumenCluster();
        }
    }, 60000);
});

// ─── Copiar al portapapeles (funciona en HTTP sin HTTPS) ─────
// 1) Intenta la API moderna (solo secure context)
// 2) Fallback con <textarea> + execCommand (sí funciona en HTTP)
async function copiarAlPortapapeles(texto) {
    texto = String(texto ?? '');

    // 1) API moderna
    if (navigator.clipboard && window.isSecureContext) {
        try {
            await navigator.clipboard.writeText(texto);
            return true;
        } catch (e) { /* caer al fallback */ }
    }

    // 2) Fallback universal
    try {
        const ta = document.createElement('textarea');
        ta.value = texto;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '0';
        ta.style.left = '-9999px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, texto.length);
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
    } catch (e) {
        console.error('[copiar]', e);
        return false;
    }
}

window.copiarAlPortapapeles = copiarAlPortapapeles;


// ═══════════════════════════════════════════════════════════════
// Modal: cambiar MI contraseña (cualquier usuario logueado)
// Llama a /api/me/password — el backend decide si es panel o clúster
// ═══════════════════════════════════════════════════════════════
function modalCambiarPassword() {
    if (document.getElementById('pwd-modal')) return;
    const html = `
        <div class="modal-bg show" id="pwd-modal"
             onclick="if(event.target===this)cerrarMiPassword()">
            <div class="modal">
                <h3><span data-ico="key"></span> Cambiar mi contraseña</h3>
                <p style="font-size:12px;color:var(--dim);margin-bottom:14px;">
                    Usuario: <b>${escapeHtml(window.USUARIO_ACTUAL || '—')}</b>
                </p>
                <div class="form-group"><label>Contraseña actual</label>
                    <input type="password" id="pwd-actual" autocomplete="current-password"></div>
                <div class="form-group"><label>Nueva contraseña (mín. 8)</label>
                    <input type="password" id="pwd-nueva" autocomplete="new-password"></div>
                <div class="form-group"><label>Repetir nueva contraseña</label>
                    <input type="password" id="pwd-nueva2" autocomplete="new-password"></div>
                <div class="modal-actions">
                    <button class="btn btn-n" onclick="cerrarMiPassword()">Cancelar</button>
                    <button class="btn btn-g" onclick="guardarMiPassword()">Cambiar</button>
                </div>
            </div>
        </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
    setTimeout(() => document.getElementById('pwd-actual')?.focus(), 50);
}

function cerrarMiPassword() {
    document.getElementById('pwd-modal')?.remove();
}

async function guardarMiPassword() {
    const actual = document.getElementById('pwd-actual').value;
    const nueva  = document.getElementById('pwd-nueva').value;
    const nueva2 = document.getElementById('pwd-nueva2').value;

    if (!actual)          { toast('Falta la contraseña actual', 'warning'); return; }
    if (nueva.length < 8) { toast('La nueva debe tener mínimo 8 caracteres', 'warning'); return; }
    if (nueva !== nueva2) { toast('Las contraseñas nuevas no coinciden', 'warning'); return; }
    if (nueva === actual) { toast('La nueva debe ser distinta a la actual', 'warning'); return; }

    try {
        const data = await api('/api/me/password', {
            method: 'POST',
            body: JSON.stringify({ actual, nueva }),
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || 'no se pudo cambiar'), 'error', 6000);
            return;
        }
        toast('Contraseña actualizada correctamente', 'success');
        cerrarMiPassword();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

window.modalCambiarPassword = modalCambiarPassword;
window.cerrarMiPassword     = cerrarMiPassword;
window.guardarMiPassword    = guardarMiPassword;

// Enter en los inputs guarda
document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && document.getElementById('pwd-modal')) {
        guardarMiPassword();
    }
});
