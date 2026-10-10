// ═══════════════════════════════════════════════════════════════
// terminal-xterm.js — Shell interactiva con PTY real (v4)
//   · Usuario SSH por nodo (desde inventario)
//   · Ctrl+C copia si hay selección; si no, SIGINT
//   · Ctrl+V pega desde portapapeles
// ═══════════════════════════════════════════════════════════════

let _xt = null, _xws = null, _xfit = null;

function _xtResize() {
    if (!_xws || _xws.readyState !== 1 || !_xt) return;
    _xws.send('\x00' + JSON.stringify({
        type: 'resize', cols: _xt.cols, rows: _xt.rows,
    }));
}

// Fit que evita que la última fila quede cortada
function _fitSeguro() {
    if (!_xfit || !_xt) return;
    try {
        _xfit.fit();
        const cont = document.getElementById('xterm-container');
        if (!cont) return;
        const screen = cont.querySelector('.xterm-screen');
        if (!screen) return;
        const cellH = screen.getBoundingClientRect().height / _xt.rows;
        const avail = cont.clientHeight - 24; // margen de seguridad
        const filasQueCaben = Math.max(5, Math.floor(avail / cellH));
        if (filasQueCaben < _xt.rows) {
            _xt.resize(_xt.cols, filasQueCaben);
        }
    } catch {}
}

function _xtOnWinResize() { _fitSeguro(); }

// Busca el usuario SSH (ansible_user) del inventario para esa IP
function _userDeNodo(ip) {
    try {
        const h = (typeof INVENTARIO !== 'undefined' && INVENTARIO.hosts || [])
            .find(x => x.ip === ip);
        return (h && h.usuario) ? h.usuario : 'cluster0';
    } catch { return 'cluster0'; }
}


// Devuelve el usuario del panel actual (para autenticarse como él)
function _usuarioSesion() {
    const el = document.querySelector('.hdr-user');
    return el ? el.textContent.trim() : '';
}

async function abrirShellInteractiva(ipForzada) {
    const ip = ipForzada || (window.Term && Term.node) || '10.4.8.10';
    const usuario = _usuarioSesion() || _userDeNodo(ip);

    const modal = document.getElementById('xterm-modal');
    if (!modal) { toast('Modal no encontrado', 'error'); return; }
    modal.style.display = 'flex';
    if (window._pintarContenedorXterm) _pintarContenedorXterm();
    document.getElementById('xterm-title').textContent =
        `Shell — ${usuario}@${ip}`;

    await new Promise(r => setTimeout(r, 80));
    const cont = document.getElementById('xterm-container');
    cont.innerHTML = '';

    const _esClaro = (document.documentElement.getAttribute('data-theme') || 'light') === 'light';
    const _temaXterm = _esClaro ? {
        background: '#ffffff', foreground: '#1a202c',
        cursor: '#1a7f37', selectionBackground: '#cbd5e0',
        black: '#000000', red: '#c1272d', green: '#1a7f37', yellow: '#b45309',
        blue: '#1e5fa0', magenta: '#8250df', cyan: '#0e7490', white: '#e5e7eb',
        brightBlack: '#6b7280', brightRed: '#dc2626', brightGreen: '#15803d',
        brightYellow: '#ca8a04', brightBlue: '#2563eb', brightMagenta: '#9333ea',
        brightCyan: '#0891b2', brightWhite: '#f9fafb',
    } : {
        background: '#0e1116', foreground: '#d8dde4',
        cursor: '#7ec699', selectionBackground: '#2e3440',
        black: '#1c1f24', red: '#e06c75', green: '#98c379', yellow: '#e5c07b',
        blue: '#61afef', magenta: '#c678dd', cyan: '#56b6c2', white: '#abb2bf',
        brightBlack: '#5c6370', brightRed: '#e06c75', brightGreen: '#98c379',
        brightYellow: '#e5c07b', brightBlue: '#61afef', brightMagenta: '#c678dd',
        brightCyan: '#56b6c2', brightWhite: '#ffffff',
    };

    _xt = new Terminal({
        cursorBlink: true,
        fontSize: 13,
        fontFamily: "'IBM Plex Mono', 'Consolas', monospace",
        theme: _temaXterm,
        scrollback: 8000,
        allowProposedApi: true,
        convertEol: false,
    });
    _xfit = new FitAddon.FitAddon();
    _xt.loadAddon(_xfit);
    _xt.open(cont);
    try { _xfit.fit(); } catch {}

    // ─── Ctrl+C / Ctrl+V estilo VS Code ──────────────────────
    _xt.attachCustomKeyEventHandler(e => {
        const ctrl = e.ctrlKey && !e.metaKey;

        // Ctrl+Shift+C / Ctrl+Shift+V → dejar que el navegador copie/pegue
        if (ctrl && e.shiftKey && (e.code === 'KeyC' || e.code === 'KeyV')) {
            return false;
        }

        // Ctrl+C con selección → copiar; sin selección → dejar pasar (SIGINT)
        if (ctrl && !e.shiftKey && e.code === 'KeyC' && e.type === 'keydown') {
            const sel = _xt.getSelection();
            if (sel && sel.length > 0) {
                _copiarAlPortapapeles(sel);
                _xt.clearSelection();
                return false;
            }
            return true;
        }

        // Ctrl+V → pegar del portapapeles
        if (ctrl && !e.shiftKey && e.code === 'KeyV' && e.type === 'keydown') {
            _pegarDelPortapapeles();
            return false;
        }

        return true;
    });

    // Click derecho → copiar si hay selección, pegar si no
    cont.addEventListener('contextmenu', e => {
        e.preventDefault();
        const sel = _xt.getSelection();
        if (sel && sel.length > 0) _copiarAlPortapapeles(sel);
        else                        _pegarDelPortapapeles();
    });

    // ─── WebSocket ────────────────────────────────────────────
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/ws/terminal?ip=${encodeURIComponent(ip)}&user=${encodeURIComponent(usuario)}`;
    _xws = new WebSocket(url);

    _xws.onopen = () => { _xtResize(); _xt.focus(); };
    _xws.onmessage = e => {
        if (typeof e.data === 'string') _xt.write(e.data);
        else _xt.write(new Uint8Array(e.data));
    };
    _xws.onclose = () => _xt && _xt.write('\r\n\x1b[33m[conexión cerrada]\x1b[0m\r\n');
    _xws.onerror = () => _xt && _xt.write('\r\n\x1b[31m[error de conexión]\x1b[0m\r\n');

    _xt.onData(d => { if (_xws && _xws.readyState === 1) _xws.send(d); });
    _xt.onResize(_xtResize);

    window.addEventListener('resize', _xtOnWinResize);
    setTimeout(_fitSeguro, 100);
    setTimeout(_fitSeguro, 300);
    setTimeout(_fitSeguro, 700);
}

// ─── Portapapeles ────────────────────────────────────────────
function _copiarAlPortapapeles(txt) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(txt).then(
            () => toast('Copiado', 'success'),
            () => _copiarFallback(txt),
        );
    } else {
        _copiarFallback(txt);
    }
}
function _copiarFallback(txt) {
    try {
        const ta = document.createElement('textarea');
        ta.value = txt;
        ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        toast(ok ? 'Copiado' : 'No se pudo copiar', ok ? 'success' : 'error');
    } catch {
        toast('No se pudo copiar', 'error');
    }
}
function _pegarDelPortapapeles() {
    if (navigator.clipboard && navigator.clipboard.readText && window.isSecureContext) {
        navigator.clipboard.readText().then(
            text => { if (text && _xws && _xws.readyState === 1) _xws.send(text); },
            () => toast('Permiso de portapapeles denegado (usa Ctrl+Shift+V)', 'warning'),
        );
    } else {
        toast('Usa Ctrl+Shift+V (HTTP sin HTTPS no permite Ctrl+V)', 'warning', 5000);
    }
}

function cerrarShellInteractiva() {
    window.removeEventListener('resize', _xtOnWinResize);
    if (_xws) { try { _xws.close(); } catch {} _xws = null; }
    if (_xt)  { try { _xt.dispose(); } catch {} _xt = null; }
    _xfit = null;
    const m = document.getElementById('xterm-modal');
    if (m) m.style.display = 'none';
}

// Esc cierra el modal si el foco no está en la terminal
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        const m = document.getElementById('xterm-modal');
        if (m && m.style.display !== 'none') {
            if (!_xt || !document.activeElement?.closest('.xterm')) {
                cerrarShellInteractiva();
            }
        }
    }
});


// Aplica colores del contenedor xterm según el tema actual


window._pintarContenedorXterm = _pintarContenedorXterm;

// Aplica colores y refuerza tamaño del contenedor xterm
function _pintarContenedorXterm() {
    const claro = (document.documentElement.getAttribute('data-theme') || 'light') === 'light';
    const cont  = document.getElementById('xterm-container');
    const modal = document.getElementById('xterm-modal');
    if (!modal) return;
    const box  = modal.querySelector('.xterm-modal');
    const head = modal.querySelector('.xterm-head');
    const bg   = claro ? '#ffffff' : '#0e1116';
    const fg   = claro ? '#1a202c' : '#d8dde4';

    modal.style.display = 'flex';
    modal.style.alignItems = 'center';
    modal.style.justifyContent = 'center';

    if (box)  { box.style.background = bg; box.style.color = fg; }
    if (head) { head.style.background = claro ? '#f5f7fa' : '#161b22';
                head.style.color = fg;
                head.style.borderBottomColor = claro ? '#cbd5e0' : '#2e3440'; }
    if (cont) { cont.style.background = bg; cont.style.color = fg; }
}

// Al cambiar el tema global, si el modal está abierto, re-pintamos y refiteamos
function _onTemaCambiado() {
    const modal = document.getElementById('xterm-modal');
    if (!modal || modal.style.display === 'none') return;
    _pintarContenedorXterm();
    if (_xt && _xt.options) {
        const claro = (document.documentElement.getAttribute('data-theme') || 'light') === 'light';
        _xt.options.theme = claro ? {
            background: '#ffffff', foreground: '#1a202c',
            cursor: '#1a7f37', selectionBackground: '#cbd5e0',
            black:'#000',red:'#c1272d',green:'#1a7f37',yellow:'#b45309',
            blue:'#1e5fa0',magenta:'#8250df',cyan:'#0e7490',white:'#e5e7eb',
            brightBlack:'#6b7280',brightRed:'#dc2626',brightGreen:'#15803d',
            brightYellow:'#ca8a04',brightBlue:'#2563eb',brightMagenta:'#9333ea',
            brightCyan:'#0891b2',brightWhite:'#f9fafb',
        } : {
            background: '#0e1116', foreground: '#d8dde4',
            cursor: '#7ec699', selectionBackground: '#2e3440',
            black:'#1c1f24',red:'#e06c75',green:'#98c379',yellow:'#e5c07b',
            blue:'#61afef',magenta:'#c678dd',cyan:'#56b6c2',white:'#abb2bf',
            brightBlack:'#5c6370',brightRed:'#e06c75',brightGreen:'#98c379',
            brightYellow:'#e5c07b',brightBlue:'#61afef',brightMagenta:'#c678dd',
            brightCyan:'#56b6c2',brightWhite:'#ffffff',
        };
    }
    setTimeout(_fitSeguro, 30);
}

// Observa cambios en data-theme
(function(){
    const obs = new MutationObserver(muts => {
        for (const m of muts) {
            if (m.attributeName === 'data-theme') _onTemaCambiado();
        }
    });
    obs.observe(document.documentElement, { attributes: true });
})();

window._fitSeguro = _fitSeguro;
window.abrirShellInteractiva  = abrirShellInteractiva;
window.cerrarShellInteractiva = cerrarShellInteractiva;
