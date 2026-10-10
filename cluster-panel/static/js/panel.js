// ═══════════════════════════════════════════════════════════════
// Helpers compartidos — Interfaz de Monitoreo I2E
// ═══════════════════════════════════════════════════════════════

window.fetchEstado = async function() {
    const res = await fetch('/api/estado');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
};

window.toast = function(msg, tipo = 'info', ms = 3000) {
    const c = document.getElementById('toast-container');
    if (!c) return;
    const el = document.createElement('div');
    el.className = `toast ${tipo}`;
    el.textContent = msg;
    c.appendChild(el);
    setTimeout(() => el.remove(), ms);
};

window.fmtBytes = function(mb) {
    if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB';
    return mb + ' MB';
};

window.fmtFecha = function(iso) {
    if (!iso) return '--';
    const d = new Date(iso);
    return d.toLocaleString('es-CO', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
    });
};

window.escapeHtml = function(s) {
    return String(s).replace(/[&<>"]/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
};

// ── Toggle de tema claro/oscuro ──────────────────────────
(function setupTheme() {
    const html = document.documentElement;
    const btn  = () => document.getElementById('theme-toggle');

    function updateIcon() {
        const b = btn();
        if (!b) return;
        b.textContent = html.dataset.theme === 'dark' ? '☀️' : '🌙';
        b.title = html.dataset.theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro';
    }

    // Esperar a que el DOM cargue
    document.addEventListener('DOMContentLoaded', () => {
        updateIcon();

        document.addEventListener('click', (e) => {
            if (!e.target.closest('#theme-toggle')) return;
            html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
            localStorage.setItem('theme', html.dataset.theme);
            updateIcon();
            // Notificar a las gráficas para que actualicen sus colores
            window.dispatchEvent(new CustomEvent('themechange', { detail: html.dataset.theme }));
        });
    });
})();

// ── Piloto de conexión con Arduino ───────────────────────
async function actualizarArduinoStatus() {
    const pill = document.getElementById('arduino-status');
    if (!pill) return;
    try {
        const r = await fetch('/api/health');
        const data = await r.json();
        const dot  = pill.querySelector('.status-dot');
        const txt  = pill.querySelector('.status-text');
        if (data.arduino) {
            pill.classList.add('online');
            pill.classList.remove('offline');
            txt.textContent = 'Arduino OK';
            pill.title = 'Arduino conectado — ' + (data.arduino_port || '/dev/ttyUSB0');
        } else {
            pill.classList.add('offline');
            pill.classList.remove('online');
            txt.textContent = 'Arduino OFF';
            pill.title = 'Sin conexión con Arduino. Verifica el puerto serie.';
        }
    } catch (e) {
        pill.classList.add('offline');
        pill.classList.remove('online');
        pill.querySelector('.status-text').textContent = 'Panel OFF';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    actualizarArduinoStatus();
    setInterval(actualizarArduinoStatus, 10000);
});

console.log('[panel.js] helpers + tema + health check cargados');
