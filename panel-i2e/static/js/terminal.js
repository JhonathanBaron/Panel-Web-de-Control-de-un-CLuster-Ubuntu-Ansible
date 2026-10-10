// ═══════════════════════════════════════════════════════════════
// terminal.js — Terminal pro v3
//   · Selector de nodo propio, sincronizado con el sidebar
//   · Textarea multilinea (heredocs, scripts)
//   · Historial persistente (↑/↓) · Ctrl+L limpiar · Tab autocompletar
//   · Copiar por bloque y copiar todo · render ANSI básico
// ═══════════════════════════════════════════════════════════════

const TKEY = {
    hist:    'panel-i2e-term-history',
    node:    'panel-i2e-term-node',
    timeout: 'panel-i2e-term-timeout',
};
const TMAX_H    = 200;
const TDEF_NODE = '10.4.8.10';
const TDEF_TMO  = 300;

const TCMDS = [
    'clear', 'ls', 'ls -la', 'pwd', 'whoami', 'id',
    'uptime', 'date', 'hostname', 'uname -a',
    'df -h', 'free -m', 'top -bn1 | head -20',
    'ps aux | head -20', 'nproc', 'cat /proc/loadavg',
    'ip a', 'ss -tuln', 'ping -c 3 8.8.8.8',
    'systemctl status', 'journalctl -n 50',
    'nvidia-smi', 'ray status', 'docker ps',
];

const Term = {
    el: {},
    hist: [],
    histIdx: -1,

    get node()   { return localStorage.getItem(TKEY.node) || TDEF_NODE; },
    set node(ip) {
        localStorage.setItem(TKEY.node, ip);
        this._paint();
        const sb = document.getElementById('objetivo');
        if (sb && sb.value !== ip) sb.value = ip;
    },

    get timeout() { return parseInt(localStorage.getItem(TKEY.timeout) || TDEF_TMO, 10); },
    set timeout(s){ localStorage.setItem(TKEY.timeout, String(s)); },

    init() {
        this.el.body  = document.getElementById('term-body');
        this.el.input = document.getElementById('term-input');
        this.el.nodo  = document.getElementById('term-nodo');
        this.el.tout  = document.getElementById('term-timeout');
        this.el.label = document.getElementById('term-label');
        if (!this.el.body || !this.el.input) return;

        this.hist = this._loadHist();
        this._fillNodos();
        document.addEventListener('inventory:ready', () => this._fillNodos());
        if (this.el.tout) this.el.tout.value = String(this.timeout);
        this._paint();
        this._bind();
    },

    _paint() {
        if (this.el.label) this.el.label.textContent = `cluster0@${this.node} ~ $`;
        if (this.el.nodo && this.el.nodo.value !== this.node) this.el.nodo.value = this.node;
    },

    _fillNodos() {
        const sel = this.el.nodo;
        if (!sel || typeof INVENTARIO === 'undefined' || !INVENTARIO.hosts) return;
        sel.innerHTML = (INVENTARIO.hosts || [])
            .filter(h => h.rol !== 'nas')
            .map(h => `<option value="${h.ip}">${escapeHtml(h.nombre)} — ${h.ip}</option>`)
            .join('');
        sel.value = this.node;
    },

    _bind() {
        const inp = this.el.input;
        const wrap = document.querySelector('.terminal-wrap');
        if (wrap && !document.getElementById('term-hint')) {
            const h = document.createElement('div');
            h.id = 'term-hint';
            h.className = 'term-hint';
            h.innerHTML = '<kbd>Enter</kbd> ejecutar · <kbd>Shift+Enter</kbd> nueva línea · <kbd>↑</kbd>/<kbd>↓</kbd> historial · <kbd>Tab</kbd> autocompletar · <kbd>Ctrl+L</kbd> limpiar';
            inp.parentNode.insertBefore(h, inp);
        }

        inp.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.run(); return; }
            if (inp.value.indexOf('\n') === -1) {
                if (e.key === 'ArrowUp')   { e.preventDefault(); this._histMove(-1); return; }
                if (e.key === 'ArrowDown') { e.preventDefault(); this._histMove(1);  return; }
                if (e.key === 'Tab')       { e.preventDefault(); this._autocomplete(); return; }
            }
            if (e.key === 'l' && e.ctrlKey) { e.preventDefault(); this.clear(); return; }
            setTimeout(() => this._resize(), 0);
        });

        if (this.el.nodo) {
            this.el.nodo.addEventListener('change', () => {
                this.node = this.el.nodo.value;
                this._write(`<span class="term-dim">[nodo → ${escapeHtml(this.node)}]</span>\n\n`);
            });
        }
        if (this.el.tout) {
            this.el.tout.addEventListener('change', () => {
                this.timeout = parseInt(this.el.tout.value, 10);
            });
        }

        const sb = document.getElementById('objetivo');
        if (sb) {
            sb.addEventListener('change', () => {
                const v = sb.value;
                if (/^\d+\.\d+\.\d+\.\d+$/.test(v)) this.node = v;
            });
        }
    },

    _resize() {
        const inp = this.el.input;
        if (!inp) return;
        inp.style.height = 'auto';
        inp.style.height = Math.min(inp.scrollHeight, 240) + 'px';
    },

    _loadHist() { try { return JSON.parse(localStorage.getItem(TKEY.hist) || '[]'); } catch { return []; } },
    _saveHist() { try { localStorage.setItem(TKEY.hist, JSON.stringify(this.hist.slice(-TMAX_H))); } catch {} },

    _histMove(dir) {
        if (!this.hist.length) return;
        if (this.histIdx === -1) this.histIdx = this.hist.length;
        this.histIdx = Math.max(0, Math.min(this.hist.length, this.histIdx + dir));
        this.el.input.value = this.hist[this.histIdx] || '';
        this._resize();
    },

    _autocomplete() {
        const v = this.el.input.value;
        if (!v) return;
        const m = TCMDS.filter(c => c.startsWith(v));
        if (m.length === 1) this.el.input.value = m[0];
        else if (m.length > 1) {
            this._write(`<span class="term-dim">${m.map(escapeHtml).join('   ')}</span>\n`);
            let p = m[0];
            for (const s of m.slice(1)) {
                let i = 0; while (i < p.length && p[i] === s[i]) i++;
                p = p.slice(0, i);
            }
            this.el.input.value = p;
        }
        this._resize();
    },

    _write(html) {
        if (!this.el || !this.el.body) {
            // El DOM aún no está listo — auto-inicializar
            this.init();
            if (!this.el || !this.el.body) return;
        }
        this.el.body.insertAdjacentHTML('beforeend', html);
        this.el.body.scrollTop = this.el.body.scrollHeight;
    },

    clear() { this.el.body.innerHTML = ''; },

    copyAll() {
        navigator.clipboard.writeText(this.el.body.innerText).then(
            () => toast('Salida copiada', 'success'),
            () => toast('No se pudo copiar', 'error'),
        );
    },

    copyBlock(id) {
        const el = document.getElementById(id);
        if (!el) return;
        navigator.clipboard.writeText(el.querySelector('.term-pre').innerText).then(
            () => toast('Bloque copiado', 'success'),
            () => toast('No se pudo copiar', 'error'),
        );
    },

    _ansi(t) {
        return escapeHtml(t)
            .replace(/\x1b\[0?m/g, '')
            .replace(/\x1b\[1m/g, '')
            .replace(/\x1b\[3([0-7])m/g, '<span class="ansi-c$1">')
            .replace(/\x1b\[[0-9;]*m/g, '');
    },

    async run() {
        const inp = this.el.input;
        const cmd = inp.value.replace(/\s+$/,'');
        if (!cmd.trim()) return;
        inp.value = '';
        this._resize();

        if (cmd.trim() === 'clear' || cmd.trim() === 'cls') { this.clear(); return; }
        if (cmd.trim() === 'history') {
            this.hist.forEach((c, i) => this._write(
                `<div class="term-dim">${String(i+1).padStart(4)}  ${escapeHtml(c)}</div>`));
            this._write('\n');
            return;
        }
        if (this.hist[this.hist.length - 1] !== cmd) this.hist.push(cmd);
        this._saveHist();

        const bid = 'tb-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        this._write(
            `<div class="term-block" id="${bid}">` +
              `<div class="term-block-head">` +
                `<span class="term-prompt">cluster0@${escapeHtml(this.node)}:~$</span> ` +
                `<span class="term-cmd">${escapeHtml(cmd.length > 200 ? cmd.slice(0,200)+'…' : cmd)}</span>` +
                `<button class="term-copy" onclick="Term.copyBlock('${bid}')" title="Copiar salida">📋</button>` +
              `</div>` +
              `<pre class="term-pre"><span class="term-dim">…</span></pre>` +
            `</div>`
        );
        const pre = document.querySelector(`#${bid} .term-pre`);

        const t0 = performance.now();
        try {
            const data = await api('/api/ejecutar', {
                method: 'POST',
                body: JSON.stringify({
                    accion:   'comando_libre',
                    objetivo: this.node,
                    extra:    cmd,
                }),
            });
            const dt = ((performance.now() - t0) / 1000).toFixed(2);
            pre.innerHTML = this._ansi(data.output || '(sin salida)');
            pre.insertAdjacentHTML('beforeend',
                `<span class="term-dim">\n— ${data.status} · ${dt}s</span>`);
        } catch (e) {
            pre.innerHTML = `<span class="term-err">Error: ${escapeHtml(e.message)}</span>`;
        }
        this.el.body.scrollTop = this.el.body.scrollHeight;
        inp.focus();
    },
};

// ─── Compatibilidad con código antiguo ───────────────────────
Object.defineProperty(window, 'terminalNodo', {
    get() { return Term.node; },
    set(v) { if (v) Term.node = v; },
    configurable: true,
});

window.abrirTerminal = function (ip) {
    if (ip) Term.node = ip;

    // Asegurar que Term esté inicializado antes de usarlo
    if (!Term.el || !Term.el.body) {
        Term.init();
    }

    cambiarTab('terminal');

    // Dar un tick para que el DOM del tab se renderice antes de escribir
    setTimeout(() => {
        if (!Term.el || !Term.el.body) return;
        Term._write(`<span class="term-dim">[conectado a ${escapeHtml(Term.node)}]</span>\n\n`);
        if (Term.el.input) Term.el.input.focus();
    }, 50);
};

window.limpiarTerminal = () => Term.clear();
window.copiarTerminal  = () => Term.copyAll();
window.Term = Term;

// Init robusto: si el DOM ya está listo, inicializa inmediato; si no,
// espera a DOMContentLoaded.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => Term.init());
} else {
    // DOM ya listo — inicializar ya
    setTimeout(() => Term.init(), 0);
}



// ─── Ejecutar comando preestablecido desde el sidebar ──────────
Term.runPreset = function(cmd) {
    if (!this.el.input) return;
    this.el.input.value = cmd;
    this.run();
};

window.irATerminalYEjecutar = function(cmd) {
    // 1) Sincronizar con el nodo objetivo del sidebar si es una IP
    const obj = document.getElementById('objetivo');
    if (obj) {
        const v = (obj.value || '').trim();
        if (/^\d+\.\d+\.\d+\.\d+$/.test(v) && window.Term) {
            Term.node = v;
        }
    }
    // 2) Ir al tab Terminal
    if (typeof cambiarTab === 'function') {
        cambiarTab('terminal');
    }
    // 3) Ejecutar tras un breve delay para que se renderice
    setTimeout(() => {
        if (window.Term && Term.runPreset) {
            Term.runPreset(cmd);
        }
    }, 150);
};
