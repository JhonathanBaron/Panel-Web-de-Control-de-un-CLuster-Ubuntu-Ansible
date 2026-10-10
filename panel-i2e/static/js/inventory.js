// ═══════════════════════════════════════════════════════════════
// Inventario dinámico: rellena los <select> desde /api/inventory
// ═══════════════════════════════════════════════════════════════

let INVENTARIO = { grupos: {}, hosts: [] };

async function cargarInventario() {
    try {
        const data = await api('/api/inventory');
        if (data.status !== 'success') throw new Error(data.output || 'error');
        INVENTARIO = data;
        rellenarSelectObjetivo();
        rellenarSelectHerramientas();
        document.dispatchEvent(new CustomEvent('inventory:ready', { detail: INVENTARIO }));
    } catch (e) {
        console.error('[inventory]', e);
        toast('No se pudo cargar el inventario: ' + e.message, 'error');
    }
}

const _ORDEN_GRUPOS = ['manager', 'compute', 'heavy', 'light', 'nas', 'cluster'];

function rellenarSelectObjetivo() {
    const sel = document.getElementById('objetivo');
    if (!sel) return;
    const prev = sel.value;

    const grupos = INVENTARIO.grupos || {};
    const hosts  = INVENTARIO.hosts  || [];

    const nombres = Object.keys(grupos).sort((a, b) => {
        const ia = _ORDEN_GRUPOS.indexOf(a), ib = _ORDEN_GRUPOS.indexOf(b);
        if (ia === -1 && ib === -1) return a.localeCompare(b);
        if (ia === -1) return 1;
        if (ib === -1) return -1;
        return ia - ib;
    });

    let html = '<option value="all">🌐 Todo (incluye NAS)</option>';
    for (const g of nombres) {
        const info = grupos[g];
        const nHosts    = (info.hosts    || []).length;
        const nChildren = (info.children || []).length;
        const etiqueta  = g.charAt(0).toUpperCase() + g.slice(1);
        let extra = '';
        if (nChildren)      extra = ` · ${nChildren} subgrupo${nChildren === 1 ? '' : 's'}`;
        else if (nHosts)    extra = ` · ${nHosts} nodo${nHosts === 1 ? '' : 's'}`;
        html += `<option value="${g}">${etiqueta}${extra}</option>`;
    }

    html += '<option disabled>──────────</option>';
    for (const h of hosts) {
        html += `<option value="${h.ip}">${escapeHtml(h.nombre)} — ${h.ip}</option>`;
    }

    sel.innerHTML = html;
    if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}

function rellenarSelectHerramientas() {
    const sel = document.getElementById('herr-nodo');
    if (!sel) return;
    const prev = sel.value;
    const hosts = (INVENTARIO.hosts || []).filter(h => h.rol !== 'nas');
    sel.innerHTML = hosts.map(h =>
        `<option value="${h.ip}">${escapeHtml(h.nombre)} (${h.ip})</option>`
    ).join('');
    if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}
