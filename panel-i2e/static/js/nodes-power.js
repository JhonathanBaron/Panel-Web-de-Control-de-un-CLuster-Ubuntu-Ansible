// ═══════════════════════════════════════════════════════════════
// Poder por nodo: WOL, apagar, reiniciar + editar MAC
// ═══════════════════════════════════════════════════════════════

async function abrirConfigNodo(ip, nombre) {
    var cfg = { mac: "", wol: false, nombre: nombre || ip };
    try {
        var data = await api('/api/nodos/config');
        if (data.nodos && data.nodos[ip]) cfg = data.nodos[ip];
    } catch (e) { /* silencio */ }

    var old = document.getElementById('modal-nodo-config');
    if (old) old.remove();

    var html = ''
        + '<div class="modal-bg show" id="modal-nodo-config" onclick="if(event.target===this)cerrarConfigNodo()">'
        + '  <div class="modal">'
        + '    <h3><span data-ico="target"></span> Configurar ' + escapeHtml(cfg.nombre) + ' <span style="font-family:var(--mono);font-size:12px;color:var(--dim);">' + ip + '</span></h3>'
        + '    <div class="form-group">'
        + '      <label>Nombre visible</label>'
        + '      <input type="text" id="nc-nombre" value="' + escapeHtml(cfg.nombre || '') + '">'
        + '    </div>'
        + '    <div class="form-group">'
        + '      <label>MAC (para Wake-on-LAN)</label>'
        + '      <input type="text" id="nc-mac" placeholder="aa:bb:cc:dd:ee:ff" value="' + escapeHtml(cfg.mac || '') + '">'
        + '      <div style="font-size:11px;color:var(--dim);margin-top:4px;">'
        + '        Acepta <code>aa:bb:cc:dd:ee:ff</code>, <code>aa-bb-cc-dd-ee-ff</code> o <code>aabbccddeeff</code>'
        + '      </div>'
        + '    </div>'
        + '    <div class="form-group">'
        + '      <label><input type="checkbox" id="nc-wol" ' + (cfg.wol ? 'checked' : '') + '> Permitir Wake-on-LAN</label>'
        + '    </div>'
        + '    <div class="modal-actions">'
        + '      <button class="btn btn-n" onclick="cerrarConfigNodo()">Cancelar</button>'
        + '      <button class="btn btn-g" onclick="guardarConfigNodo(\'' + ip + '\')">Guardar</button>'
        + '    </div>'
        + '  </div>'
        + '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
    var macIn = document.getElementById('nc-mac');
    if (macIn) macIn.focus();
}

function cerrarConfigNodo() {
    var m = document.getElementById('modal-nodo-config');
    if (m) m.remove();
}

async function guardarConfigNodo(ip) {
    var cambios = {
        nombre: document.getElementById('nc-nombre').value.trim(),
        mac:    document.getElementById('nc-mac').value.trim(),
        wol:    document.getElementById('nc-wol').checked,
    };
    try {
        var data = await api('/api/nodos/' + ip + '/config', {
            method: 'PUT', body: JSON.stringify(cambios)
        });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error'); return;
        }
        toast('Configuración guardada', 'success');
        cerrarConfigNodo();
        if (typeof cargarNodos === 'function') cargarNodos();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function accionPowerNodo(ip, accion, nombre) {
    var textos = {
        on:     ['Encender',  '¿Enviar Wake-on-LAN a ' + nombre + '?'],
        off:    ['Apagar',    '¿Apagar ' + nombre + '?' + String.fromCharCode(10,10) + 'Se perderán los procesos en ejecución.'],
        reboot: ['Reiniciar', '¿Reiniciar ' + nombre + '?' + String.fromCharCode(10,10) + 'Se perderán los procesos en ejecución.'],
    };
    var t = textos[accion] || ['?', '¿Continuar?'];
    var verbo = t[0], pregunta = t[1];
    if (!confirm(pregunta)) return;

    toast(verbo + ' ' + nombre + '…', 'info', 3000);
    try {
        var data = await api('/api/nodos/' + ip + '/power/' + accion, { method: 'POST' });
        if (data.status === 'success') {
            toast(verbo + ': OK', 'success');
        } else {
            toast(verbo + ' falló: ' + (data.output || '').slice(0, 150), 'error', 6000);
        }
        console.log(data.output);
        setTimeout(function () {
            if (typeof cargarNodos === 'function') cargarNodos();
        }, 2000);
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// ─── Inyectar botones en las cards ──────────────────────────
function _npInyectarBotones() {
    var grid = document.getElementById('nodos-grid');
    if (!grid) return;

    grid.querySelectorAll('.nodo-card').forEach(function (card) {
        if (card.dataset.powerBtns === '1') return;
        card.dataset.powerBtns = '1';

        var ip = card.id.replace(/^nodo-/, '').replace(/-/g, '.');
        var nombreEl = card.querySelector('.nodo-nombre');
        var nombre = nombreEl ? nombreEl.textContent.trim() : ip;

        var barra = document.createElement('div');
        barra.className = 'nodo-power-bar';
        barra.innerHTML = ''
            + '<button class="np-btn np-on"  title="Encender (WOL)"  data-pow="on"><span data-ico="zap"></span></button>'
            + '<button class="np-btn np-reb" title="Reiniciar"        data-pow="reboot"><span data-ico="refresh"></span></button>'
            + '<button class="np-btn np-off" title="Apagar"           data-pow="off"><span data-ico="x"></span></button>'
            + '<button class="np-btn np-cfg" title="Configurar MAC"   data-pow="config"><span data-ico="wrench"></span></button>';

        barra.querySelectorAll('.np-btn').forEach(function (b) {
            b.addEventListener('click', function (e) {
                e.stopPropagation();
                var acc = b.dataset.pow;
                if (acc === 'config') abrirConfigNodo(ip, nombre);
                else                  accionPowerNodo(ip, acc, nombre);
            });
        });
        card.appendChild(barra);
    });
}

document.addEventListener('DOMContentLoaded', function () {
    setTimeout(_npInyectarBotones, 5000);
    setInterval(_npInyectarBotones, 8000);
});

window.abrirConfigNodo   = abrirConfigNodo;
window.cerrarConfigNodo  = cerrarConfigNodo;
window.guardarConfigNodo = guardarConfigNodo;
window.accionPowerNodo   = accionPowerNodo;

// ═══════════════════════════════════════════════════════════════
// Auto-detección de MACs (equivalente a mac.yml)
// ═══════════════════════════════════════════════════════════════

async function detectarMacsAuto() {
    if (!confirm('¿Detectar MACs de TODOS los nodos vía ansible setup?\n\n' +
                 'Los nodos deben estar encendidos y accesibles por SSH.\n' +
                 'Las MACs se guardarán en data/nodes.json automáticamente.')) return;

    toast('Consultando MACs a todos los nodos…', 'info', 6000);

    if (typeof _cmdMostrar === 'function') {
        _cmdMostrar({
            titulo: 'Detectando MACs en el clúster',
            subtitulo: 'Consultando ansible setup…',
            output: 'Puede tardar 30-60s…',
            status: 'running',
        });
    }

    try {
        const data = await api('/api/nodos/detectar-macs', { method: 'POST' });

        if (data.status !== 'success') {
            if (typeof _cmdMostrar === 'function') {
                _cmdMostrar({
                    titulo: 'Error detectando MACs',
                    subtitulo: '',
                    output: (data.output || '') + '\n\n' + (data.raw || ''),
                    status: 'error',
                });
            }
            toast('Error: ' + (data.output || '').slice(0, 200), 'error', 8000);
            return;
        }

        // Tabla de resultados
        const ips = Object.keys(data.detectadas || {}).sort(function(a, b) {
            const pa = a.split('.').map(Number), pb = b.split('.').map(Number);
            for (let i = 0; i < 4; i++) if (pa[i] !== pb[i]) return pa[i] - pb[i];
            return 0;
        });

        let lineas = [];
        lineas.push('IP               MAC');
        lineas.push('----------------------------------------');
        for (const ip of ips) {
            lineas.push(ip.padEnd(15) + '  ' + data.detectadas[ip]);
        }
        lineas.push('');
        lineas.push('OK: ' + data.n + ' de ' + data.hosts_consultados + ' nodos actualizados');
        if (data.errores && data.errores.length) {
            lineas.push('');
            lineas.push('Nodos con error:');
            for (const e of data.errores) {
                lineas.push('  ' + e.ip + ': ' + e.error);
            }
        }

        if (typeof _cmdMostrar === 'function') {
            _cmdMostrar({
                titulo: 'MACs detectadas',
                subtitulo: data.n + ' de ' + data.hosts_consultados + ' nodos',
                output: lineas.join('\n'),
                status: 'success',
            });
        }

        toast(data.n + ' MAC(s) guardadas', 'success');
        if (typeof cargarNodos === 'function') cargarNodos();
    } catch (e) {
        toast('Error: ' + e.message, 'error', 8000);
    }
}

async function detectarMacSoloNodo(ip) {
    const boton = document.getElementById('nc-btn-auto');
    if (boton) { boton.disabled = true; boton.textContent = 'Buscando…'; }

    toast('Detectando MAC de ' + ip + '…', 'info', 4000);
    try {
        const data = await api('/api/nodos/detectar-macs', { method: 'POST' });
        if (data.status !== 'success') {
            toast('Error: ' + (data.output || ''), 'error');
            return;
        }
        const mac = data.detectadas[ip];
        if (!mac) {
            toast('No se pudo detectar la MAC de ' + ip + ' (¿está encendido?)', 'warning', 5000);
            return;
        }
        const input = document.getElementById('nc-mac');
        if (input) input.value = mac;
        toast('MAC detectada: ' + mac, 'success');
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    } finally {
        if (boton) { boton.disabled = false; boton.textContent = 'Auto'; }
    }
}

window.detectarMacsAuto    = detectarMacsAuto;
window.detectarMacSoloNodo = detectarMacSoloNodo;

// ═══════════════════════════════════════════════════════════════
// WOL a todos los nodos con wol=true (reemplaza al Mac.sh)
// ═══════════════════════════════════════════════════════════════

async function wolTodos() {
    if (!confirm('¿Enviar Wake-on-LAN a TODOS los nodos con wol=true?\n\n' +
                 'Se usa la MAC guardada en cada nodo.')) return;

    toast('Enviando magic packets…', 'info', 3000);

    if (typeof _cmdMostrar === 'function') {
        _cmdMostrar({
            titulo: 'Wake-on-LAN (todos)',
            subtitulo: 'Enviando a nodos con wol=true',
            output: 'Enviando…',
            status: 'running',
        });
    }

    try {
        const data = await api('/api/nodos/wol-todos', { method: 'POST' });
        if (typeof _cmdMostrar === 'function') {
            _cmdMostrar({
                titulo: 'Wake-on-LAN (todos)',
                subtitulo: data.n_enviados + ' enviados · ' +
                           data.n_omitidos + ' omitidos · ' +
                           data.n_errores + ' errores',
                output: data.output || '(sin salida)',
                status: data.status === 'success' ? 'success' : 'error',
            });
        }
        const msg = data.n_enviados + ' magic packet(s) enviados';
        toast(msg, data.n_errores ? 'warning' : 'success');
    } catch (e) {
        toast('Error: ' + e.message, 'error', 6000);
    }
}

window.wolTodos = wolTodos;


// ═══════════════════════════════════════════════════════════════
// WOL mejorado — no bloquea la UI
// ═══════════════════════════════════════════════════════════════
async function wolTodosV2() {
    // Bloqueo visual inmediato
    const btns = document.querySelectorAll('button');
    let btn = null;
    btns.forEach(b => { if (b.textContent.includes('Wake-on-LAN')) btn = b; });
    const textoOrig = btn ? btn.innerHTML : '';
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ Enviando…'; }

    toast('Enviando paquete mágico a los nodos…', 'info');

    try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 15000);   // 15s máx

        const data = await api('/api/nodos/wol-todos', {
            method: 'POST',
            signal: ctrl.signal,
        });
        clearTimeout(t);

        if (data.status === 'success') {
            toast(
                `WOL enviado a ${data.n_enviados} nodo(s)` +
                (data.n_omitidos ? ` · ${data.n_omitidos} omitido(s)` : '') +
                (data.n_errores ? ` · ${data.n_errores} error(es)` : ''),
                data.n_errores ? 'warning' : 'success',
                6000,
            );
        } else {
            toast('WOL: ' + (data.output || 'error').slice(0, 200), 'error');
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            toast('WOL: la petición tardó demasiado (posible red sin broadcast)', 'warning', 6000);
        } else {
            toast('WOL: ' + e.message, 'error');
        }
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = textoOrig; }
    }
}

// Sobrescribe la función antigua
window.wolTodos = wolTodosV2;
