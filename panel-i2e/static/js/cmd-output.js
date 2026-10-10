// ═══════════════════════════════════════════════════════════════
// Modal de output para comandos rápidos (ping, ram, disco…)
// ═══════════════════════════════════════════════════════════════

function _cmdEsc(str) {
    return escapeHtml(String(str == null ? '' : str));
}

function _cmdMostrar(opts) {
    var id = 'modal-cmd-out';
    var old = document.getElementById(id);
    if (old) old.remove();

    var ok = opts.status === 'success';
    var running = opts.status === 'running';
    var badgeCls = running ? 'run' : (ok ? 'ok' : 'err');
    var badgeTxt = running ? '⏳ RUN' : (ok ? '✓ OK' : '✗ ERROR');
    var icono = running ? 'refresh' : (ok ? 'check' : 'x');

    var html = ''
        + '<div class="modal-bg show" id="' + id + '" onclick="if(event.target===this)cerrarCmdOutput()">'
        + '  <div class="modal modal-cmd">'
        + '    <div class="cmd-head">'
        + '      <div class="cmd-title">'
        + '        <span data-ico="' + icono + '"></span>'
        + '        <b>' + _cmdEsc(opts.titulo) + '</b>'
        + (opts.subtitulo ? '<span class="cmd-sub">' + _cmdEsc(opts.subtitulo) + '</span>' : '')
        + '      </div>'
        + '      <div class="cmd-badge ' + badgeCls + '">' + badgeTxt + '</div>'
        + '      <button class="hdr-btn" onclick="cerrarCmdOutput()" title="Cerrar">'
        + '        <span data-ico="x"></span>'
        + '      </button>'
        + '    </div>'
        + '    <pre class="cmd-out" id="cmd-out-pre">' + _cmdEsc(opts.output || '(sin salida)') + '</pre>'
        + '    <div class="cmd-foot">'
        + '      <button class="btn btn-b" onclick="cmdCopiarOutput()">'
        + '        <span data-ico="copy"></span>Copiar'
        + '      </button>'
        + '      <button class="btn btn-b" onclick="cmdEnviarATerminal()">'
        + '        <span data-ico="terminal"></span>Ver en terminal'
        + '      </button>'
        + '      <div style="flex:1;"></div>'
        + '      <button class="btn btn-n" onclick="cerrarCmdOutput()">Cerrar</button>'
        + '    </div>'
        + '  </div>'
        + '</div>';

    document.body.insertAdjacentHTML('beforeend', html);
}

function cerrarCmdOutput() {
    var m = document.getElementById('modal-cmd-out');
    if (m) m.remove();
}

async function cmdCopiarOutput() {
    var pre = document.getElementById('cmd-out-pre');
    if (!pre) return;
    var ok = await copiarAlPortapapeles(pre.textContent);
    toast(ok ? 'Copiado' : 'No se pudo copiar', ok ? 'success' : 'error');
}

function cmdEnviarATerminal() {
    var pre = document.getElementById('cmd-out-pre');
    if (!pre) return;
    var txt = pre.textContent;
    cerrarCmdOutput();
    cambiarTab('terminal');
    var body = document.getElementById('term-body');
    if (body) {
        body.insertAdjacentHTML('beforeend',
            '<span class="term-info">───── desde modal ─────</span>' + String.fromCharCode(10) +
            escapeHtml(txt) + String.fromCharCode(10, 10));
        body.scrollTop = body.scrollHeight;
    }
}

async function cmdRapidoConOutput(accion, etiqueta) {
    var sel = document.getElementById('objetivo');
    var objetivo = (sel && sel.value) || 'all';
    var objetivoTxt = (sel && sel.options[sel.selectedIndex]) ? sel.options[sel.selectedIndex].text : objetivo;

    _cmdMostrar({
        titulo: etiqueta || accion,
        subtitulo: objetivoTxt,
        output: 'Ejecutando…',
        status: 'running',
    });

    try {
        var data = await api('/api/ejecutar', {
            method: 'POST',
            body: JSON.stringify({ accion: accion, objetivo: objetivo, extra: '' })
        });
        _cmdMostrar({
            titulo: etiqueta || accion,
            subtitulo: objetivoTxt,
            output: data.output || '(sin salida)',
            status: data.status === 'success' ? 'success' : 'error',
        });
    } catch (e) {
        _cmdMostrar({
            titulo: etiqueta || accion,
            subtitulo: objetivoTxt,
            output: 'Error: ' + e.message,
            status: 'error',
        });
    }
}

// Sobrescribir el cmdRapido original para que use el modal
window.cmdRapido = function (accion) {
    var etiquetas = {
        ping:          'Ping a nodos',
        recursos:      'Uso de RAM',
        espacio_disco: 'Espacio en disco',
        wakeonlan:     'Wake-on-LAN (todos)',
        reboot:        'Reiniciar',
        poweroff:      'Apagar',
    };
    return cmdRapidoConOutput(accion, etiquetas[accion] || accion);
};

window.cerrarCmdOutput    = cerrarCmdOutput;
window.cmdCopiarOutput    = cmdCopiarOutput;
window.cmdEnviarATerminal = cmdEnviarATerminal;
window.cmdRapidoConOutput = cmdRapidoConOutput;
