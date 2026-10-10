// ═══════════════════════════════════════════════════════════════
// Sparklines de CPU/RAM/Disco en las cards de nodo
// ═══════════════════════════════════════════════════════════════

const _SPARK_W = 62;
const _SPARK_H = 16;

// ─── Generar SVG de la serie ─────────────────────────────────
function _sparkSvg(series, campo, color) {
    const vals = series
        .map(m => m[campo])
        .filter(v => typeof v === 'number' && !isNaN(v));
    if (vals.length < 2) return '';

    const n = vals.length;
    const stepX = _SPARK_W / (n - 1);
    const path = vals.map((v, i) => {
        const x = i * stepX;
        const clamped = Math.max(0, Math.min(100, v));
        const y = _SPARK_H - (clamped / 100) * _SPARK_H;
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(' ');

    return `<svg class="spark" viewBox="0 0 ${_SPARK_W} ${_SPARK_H}"
                preserveAspectRatio="none" aria-hidden="true">
        <path d="${path}" fill="none" stroke="${color}"
              stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
}

// ─── Colores por umbral ──────────────────────────────────────
function _colorMetrica(campo, valor) {
    // Rojo si el último valor es alto
    if (valor >= 85) return 'var(--red)';
    if (valor >= 70) return 'var(--amber)';
    return {
        cpu:  'var(--blue)',
        ram:  'var(--amber)',
        disk: 'var(--green)',
    }[campo] || 'var(--blue)';
}

// ─── Poner el sparkline bajo una .metrica-mini ───────────────
function _ponerSpark(cont, series, campo) {
    if (!cont) return;
    // Valor actual = último de la serie
    const valores = series.map(m => m[campo]).filter(v => typeof v === 'number');
    const ultimo = valores.length ? valores[valores.length - 1] : 0;
    const color = _colorMetrica(campo, ultimo);

    let slot = cont.querySelector('.spark-slot');
    if (!slot) {
        slot = document.createElement('div');
        slot.className = 'spark-slot';
        cont.appendChild(slot);
    }
    slot.innerHTML = _sparkSvg(series, campo, color);
    slot.title = `${valores.length} muestras · último ${ultimo}%`;
}

// ─── Dibujar en todas las cards visibles ─────────────────────
async function dibujarSparklines() {
    const grid = document.getElementById('nodos-grid');
    if (!grid) return;

    const cards = grid.querySelectorAll('.nodo-card');
    if (cards.length === 0) return;

    // Extraer IPs
    const ips = Array.from(cards)
        .map(c => c.id.replace(/^nodo-/, '').replace(/-/g, '.'))
        .filter(ip => ip.split('.').length === 4);
    if (ips.length === 0) return;

    let data;
    try {
        data = await api(`/api/metrics/sparklines?ips=${ips.join(',')}&last=60`);
    } catch (e) {
        console.warn('[sparklines]', e.message);
        return;
    }

    const series = data.sparklines || {};

    for (const ip of ips) {
        const s = series[ip] || [];
        if (s.length < 2) continue;

        const card = document.getElementById('nodo-' + ip.replace(/\./g, '-'));
        if (!card) continue;

        // Evitar redibujar si no hay muestras nuevas
        const key = s.length + ':' + (s[s.length - 1]?.ts || '');
        if (card.dataset.sparkKey === key) continue;
        card.dataset.sparkKey = key;

        const metricas = card.querySelectorAll('.metrica-mini');
        if (metricas.length < 3) continue;
        _ponerSpark(metricas[0], s, 'cpu');
        _ponerSpark(metricas[1], s, 'ram');
        _ponerSpark(metricas[2], s, 'disk');
    }
}

// ─── Modal: ver histórico grande al pulsar una card ──────────
async function verHistoricoNodo(ip) {
    // Este modal se abre con el botón "Histórico" que añadimos al detalle
    let data;
    try {
        const [res, stats] = await Promise.all([
            api(`/api/metrics/sparklines?ips=${ip}&last=200`),
            api(`/api/metrics/stats/${ip}?last=200`),
        ]);
        data = { series: (res.sparklines || {})[ip] || [], stats: stats.stats || {} };
    } catch (e) {
        toast('Error: ' + e.message, 'error');
        return;
    }

    const s = data.series;
    if (s.length === 0) {
        toast('Sin histórico aún para ' + ip, 'warning');
        return;
    }

    const html = `
        <div class="modal-bg show" id="modal-historico"
             onclick="if(event.target===this)this.remove()">
            <div class="modal" style="max-width:820px;">
                <h3><span data-ico="chart"></span> Histórico de ${escapeHtml(ip)}</h3>
                <div class="historico-grid">
                    <div class="historico-item">
                        <div class="historico-lbl">CPU</div>
                        <div class="historico-spark">${_sparkSvgGrande(s, 'cpu', 'var(--blue)')}</div>
                        <div class="historico-stats">
                            avg ${data.stats.cpu_avg ?? '—'}% · max ${data.stats.cpu_max ?? '—'}%
                        </div>
                    </div>
                    <div class="historico-item">
                        <div class="historico-lbl">RAM</div>
                        <div class="historico-spark">${_sparkSvgGrande(s, 'ram', 'var(--amber)')}</div>
                        <div class="historico-stats">
                            avg ${data.stats.ram_avg ?? '—'}% · max ${data.stats.ram_max ?? '—'}%
                        </div>
                    </div>
                    <div class="historico-item">
                        <div class="historico-lbl">Disco</div>
                        <div class="historico-spark">${_sparkSvgGrande(s, 'disk', 'var(--green)')}</div>
                        <div class="historico-stats">
                            ${s.length} muestras
                        </div>
                    </div>
                </div>
                <div class="historico-meta">
                    Primera muestra: ${escapeHtml(data.stats.primera || '—')}<br>
                    Última muestra: ${escapeHtml(data.stats.ultima || '—')}
                </div>
                <div class="modal-actions">
                    <button class="btn btn-n" onclick="document.getElementById('modal-historico').remove()">
                        Cerrar
                    </button>
                </div>
            </div>
        </div>`;
    document.getElementById('modal-historico')?.remove();
    document.body.insertAdjacentHTML('beforeend', html);
}

function _sparkSvgGrande(series, campo, color) {
    const W = 700, H = 100;
    const vals = series.map(m => m[campo]).filter(v => typeof v === 'number');
    if (vals.length < 2) return '<div class="empty" style="padding:20px;">Sin datos</div>';
    const stepX = W / (vals.length - 1);
    const path = vals.map((v, i) => {
        const x = i * stepX;
        const y = H - (Math.max(0, Math.min(100, v)) / 100) * H;
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(' ');
    const area = `${path} L ${W} ${H} L 0 ${H} Z`;
    return `<svg class="spark-lg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <path d="${area}" fill="${color}" fill-opacity="0.12"/>
        <path d="${path}" fill="none" stroke="${color}" stroke-width="1.6"
              stroke-linejoin="round" stroke-linecap="round"/>
        <line x1="0" y1="${H*0.15}" x2="${W}" y2="${H*0.15}"
              stroke="var(--border)" stroke-dasharray="3 3" stroke-width="1"/>
    </svg>`;
}

// ─── Arranque ────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Primera pasada después de que cargarNodos() termine
    setTimeout(dibujarSparklines, 4000);

    // Refrescar cada 30s si estamos en Estado
    setInterval(() => {
        const t = document.querySelector('.tab[data-tab="estado"]');
        if (t && t.classList.contains('activo')) dibujarSparklines();
    }, 60000);

    // Al cambiar a Estado, redibujar
    const tabEstado = document.querySelector('.tab[data-tab="estado"]');
    if (tabEstado) {
        tabEstado.addEventListener('click', () => {
            setTimeout(dibujarSparklines, 1500);
        });
    }
});

window.dibujarSparklines = dibujarSparklines;
window.verHistoricoNodo   = verHistoricoNodo;
