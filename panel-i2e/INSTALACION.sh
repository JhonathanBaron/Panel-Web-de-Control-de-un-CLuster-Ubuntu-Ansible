#!/usr/bin/env bash
#
# instalacion.sh — Instalador del Panel de Control I2E
#
# Uso:
#   cd /ruta/al/panel-i2e
#   bash scripts/instalacion.sh
#
# Este script instala y configura el panel en el nodo manager del clúster.
# Es idempotente: puede ejecutarse varias veces sin efectos adversos.
#
# Autor: Equipo I2E — Universidad Pedagógica y Tecnológica de Colombia
# Licencia: Uso exclusivo del clúster I2E
#
set -euo pipefail

# ────────────────────────────────────────────────────────────────
# Variables globales
# ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROYECTO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PANEL_USER=""
PANEL_PORT=""
MANAGER_IP=""
WORKER_IPS=""
NAS_IP=""
ANSIBLE_DIR=""
NAS_BASE=""
ADMIN_USER=""
ADMIN_PASSWORD=""

# Colores para la salida (se desactivan si no hay terminal interactiva)
if [ -t 1 ]; then
    C_RESET=$'\033[0m'
    C_INFO=$'\033[1;34m'
    C_OK=$'\033[1;32m'
    C_WARN=$'\033[1;33m'
    C_ERR=$'\033[1;31m'
else
    C_RESET=""; C_INFO=""; C_OK=""; C_WARN=""; C_ERR=""
fi

# ────────────────────────────────────────────────────────────────
# Utilidades de salida
# ────────────────────────────────────────────────────────────────
msg_info()  { printf '%s[INFO]%s  %s\n' "$C_INFO" "$C_RESET" "$*"; }
msg_ok()    { printf '%s[ OK ]%s  %s\n' "$C_OK"   "$C_RESET" "$*"; }
msg_warn()  { printf '%s[WARN]%s  %s\n' "$C_WARN" "$C_RESET" "$*"; }
msg_err()   { printf '%s[FAIL]%s  %s\n' "$C_ERR"  "$C_RESET" "$*" >&2; }

msg_seccion() {
    printf '\n%s══ %s ══%s\n' "$C_INFO" "$*" "$C_RESET"
}

abortar() {
    msg_err "$*"
    exit 1
}

# Pregunta con valor por defecto. Devuelve la respuesta en $REPLY.
preguntar() {
    local prompt="$1"
    local default="${2:-}"
    local respuesta=""

    if [ -n "$default" ]; then
        printf '%s [%s]: ' "$prompt" "$default"
    else
        printf '%s: ' "$prompt"
    fi
    read -r respuesta
    if [ -z "$respuesta" ] && [ -n "$default" ]; then
        REPLY="$default"
    else
        REPLY="$respuesta"
    fi
}

# Pregunta sí/no. Devuelve 0 si sí, 1 si no.
preguntar_sn() {
    local prompt="$1"
    local default="${2:-n}"
    local respuesta=""
    local sufijo="[s/N]"
    [ "$default" = "s" ] && sufijo="[S/n]"

    printf '%s %s: ' "$prompt" "$sufijo"
    read -r respuesta
    respuesta="${respuesta:-$default}"
    [[ "$respuesta" =~ ^[sS]$|^[sS][iI]$ ]]
}

# ────────────────────────────────────────────────────────────────
# Validadores
# ────────────────────────────────────────────────────────────────
validar_ip() {
    local ip="$1"
    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
    local IFS='.'
    local -a partes=($ip)
    for p in "${partes[@]}"; do
        [ "$p" -ge 0 ] && [ "$p" -le 255 ] || return 1
    done
    return 0
}

validar_usuario() {
    local u="$1"
    [[ "$u" =~ ^[a-z][a-z0-9_-]{1,31}$ ]]
}

validar_puerto() {
    local p="$1"
    [[ "$p" =~ ^[0-9]+$ ]] && [ "$p" -ge 1 ] && [ "$p" -le 65535 ]
}

# ────────────────────────────────────────────────────────────────
# 1. Banner y validaciones iniciales
# ────────────────────────────────────────────────────────────────
mostrar_banner() {
    clear 2>/dev/null || true
    cat <<'EOF'
════════════════════════════════════════════════════════════════
  Panel de Control I2E — Instalador
  Universidad Pedagógica y Tecnológica de Colombia
════════════════════════════════════════════════════════════════

Este instalador configura el panel en el nodo manager del clúster.
Realizará las siguientes acciones:

  · Verificar dependencias del sistema
  · Crear la estructura del proyecto
  · Generar la configuración inicial
  · Instalar el servicio del sistema
  · Arrancar y verificar el panel

Es seguro ejecutarlo varias veces sobre la misma instalación.
Los archivos existentes no se sobrescriben sin confirmación.

EOF
    printf 'Presione Enter para continuar, o Ctrl+C para cancelar. '
    read -r _
}

validar_contexto() {
    [ -f "$PROYECTO_DIR/app.py" ] \
        || abortar "No se encontró app.py en $PROYECTO_DIR. Ejecute el script desde dentro del repositorio."
    [ -f "$PROYECTO_DIR/requirements.txt" ] \
        || abortar "No se encontró requirements.txt. El repositorio está incompleto."

    if [ "$EUID" -eq 0 ]; then
        abortar "No ejecute este script como root. Use un usuario normal con acceso a sudo."
    fi

    if ! sudo -n true 2>/dev/null; then
        msg_info "El script necesita privilegios de sudo. Es posible que se le solicite la contraseña."
        sudo true || abortar "No se obtuvieron privilegios de sudo."
    fi

    msg_ok "Directorio del proyecto: $PROYECTO_DIR"
}

# ────────────────────────────────────────────────────────────────
# 2. Preguntas interactivas
# ────────────────────────────────────────────────────────────────
recoger_datos() {
    msg_seccion "Configuración del clúster"
    printf 'Responda las siguientes preguntas. Pulse Enter para aceptar el valor por defecto.\n\n'

    # Usuario del panel
    local default_user="${USER}"
    while true; do
        preguntar "Usuario del sistema que ejecutará el panel" "$default_user"
        if validar_usuario "$REPLY" && id "$REPLY" >/dev/null 2>&1; then
            PANEL_USER="$REPLY"
            break
        fi
        msg_warn "El usuario '$REPLY' no es válido o no existe en el sistema."
    done

    # Puerto del panel
    while true; do
        preguntar "Puerto del panel web" "7000"
        if validar_puerto "$REPLY"; then
            PANEL_PORT="$REPLY"
            break
        fi
        msg_warn "Puerto inválido. Rango permitido: 1–65535."
    done

    # IP del manager
    while true; do
        preguntar "Dirección IP del nodo manager"
        if validar_ip "$REPLY"; then
            MANAGER_IP="$REPLY"
            break
        fi
        msg_warn "Dirección IP inválida."
    done

    # IPs de workers
    printf '\nIngrese las direcciones IP de los nodos worker, separadas por espacios.\n'
    printf 'Ejemplo: 10.4.8.11 10.4.8.12 10.4.8.13\n'
    preguntar "Direcciones de los workers"
    WORKER_IPS="$REPLY"

    # IP del NAS
    while true; do
        preguntar "Dirección IP del servidor NAS"
        if validar_ip "$REPLY"; then
            NAS_IP="$REPLY"
            break
        fi
        msg_warn "Dirección IP inválida."
    done

    # Directorio de Ansible
    preguntar "Directorio del proyecto Ansible" "$HOME/cluster-i2e"
    ANSIBLE_DIR="$REPLY"

    # Base del NAS para el panel
    preguntar "Directorio base del NAS para el panel" "/srv/nas/home-panel"
    NAS_BASE="$REPLY"

    # Usuario administrador del panel
    printf '\nCuenta inicial de administrador del panel.\n'
    preguntar "Nombre del administrador" "Cluster0"
    ADMIN_USER="$REPLY"

    while true; do
        printf 'Contraseña del administrador (mínimo 8 caracteres): '
        read -rs ADMIN_PASSWORD
        printf '\n'
        if [ "${#ADMIN_PASSWORD}" -ge 8 ]; then
            printf 'Confirme la contraseña: '
            local confirmacion
            read -rs confirmacion
            printf '\n'
            if [ "$ADMIN_PASSWORD" = "$confirmacion" ]; then
                break
            fi
            msg_warn "Las contraseñas no coinciden."
        else
            msg_warn "La contraseña debe tener al menos 8 caracteres."
        fi
    done

    # Confirmación
    printf '\n'
    msg_seccion "Resumen de la configuración"
    cat <<EOF
  Usuario del panel:    $PANEL_USER
  Puerto del panel:     $PANEL_PORT
  IP del manager:       $MANAGER_IP
  IPs de workers:       $WORKER_IPS
  IP del NAS:           $NAS_IP
  Directorio Ansible:   $ANSIBLE_DIR
  Base del NAS:         $NAS_BASE
  Administrador:        $ADMIN_USER
EOF
    printf '\n'
    preguntar_sn "¿Los datos son correctos?" "s" \
        || abortar "Instalación cancelada por el usuario."
}

# ────────────────────────────────────────────────────────────────
# 3. Verificación e instalación de dependencias
# ────────────────────────────────────────────────────────────────
verificar_dependencias() {
    msg_seccion "Verificación de dependencias"

    local faltantes=()
    local instalar=()

    # Paquetes que deben estar (comando: paquete apt)
    local requeridos=(
        "python3:python3"
        "python3-venv:python3-venv"
        "pip3:python3-pip"
        "git:git"
        "ssh:openssh-client"
        "curl:curl"
        "nfs-common:nfs-common"
    )

    for par in "${requeridos[@]}"; do
        local cmd="${par%%:*}"
        local pkg="${par##*:}"
        if command -v "$cmd" >/dev/null 2>&1; then
            msg_ok "$cmd"
        else
            msg_warn "$cmd no encontrado (paquete: $pkg)"
            faltantes+=("$pkg")
            instalar+=("$pkg")
        fi
    done

    # Ansible se verifica aparte (versión >= 2.15)
    if command -v ansible >/dev/null 2>&1; then
        local ver
        ver=$(ansible --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        if [ -n "$ver" ] && awk "BEGIN{exit !($ver >= 2.15)}"; then
            msg_ok "ansible $ver"
        else
            msg_warn "ansible versión $ver es anterior a 2.15"
            instalar+=("ansible")
        fi
    else
        msg_warn "ansible no encontrado"
        instalar+=("ansible")
    fi

    if [ "${#instalar[@]}" -gt 0 ]; then
        printf '\nSe instalarán los siguientes paquetes del sistema:\n'
        printf '  %s\n' "${instalar[@]}"
        printf '\n'
        preguntar_sn "¿Instalar ahora?" "s" \
            || abortar "Instale manualmente los paquetes faltantes y vuelva a ejecutar."

        sudo apt-get update
        sudo apt-get install -y "${instalar[@]}"
        msg_ok "Paquetes instalados"
    else
        msg_ok "Todas las dependencias están presentes"
    fi

    # Verificar la versión de Python (>= 3.10)
    local py_ver
    py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    awk "BEGIN{exit !($py_ver >= 3.10)}" \
        || abortar "Se requiere Python 3.10 o superior. Versión detectada: $py_ver"
    msg_ok "python3 $py_ver"
}

# ────────────────────────────────────────────────────────────────
# 4. Estructura de directorios
# ────────────────────────────────────────────────────────────────
crear_estructura() {
    msg_seccion "Estructura de directorios"

    local dirs=(
        "$PROYECTO_DIR/data"
        "$PROYECTO_DIR/data/tasks"
        "$PROYECTO_DIR/data/inventory-backups"
        "$PROYECTO_DIR/data/playbooks-backup"
        "$PROYECTO_DIR/logs"
    )

    for d in "${dirs[@]}"; do
        mkdir -p "$d"
        msg_ok "Directorio: $d"
    done
}

# ────────────────────────────────────────────────────────────────
# 5. Generación de config.local.py
# ────────────────────────────────────────────────────────────────
generar_config_local() {
    msg_seccion "Archivo de configuración local"

    local destino="$PROYECTO_DIR/config.local.py"

    if [ -f "$destino" ]; then
        msg_warn "$destino ya existe"
        if ! preguntar_sn "¿Sobrescribir con la nueva configuración?" "n"; then
            msg_info "Se conserva la configuración existente."
            return 0
        fi
        cp "$destino" "$destino.bak.$(date +%Y%m%d-%H%M%S)"
        msg_info "Copia de seguridad creada."
    fi

    # Formatear lista de workers como array de Python
    local workers_py="[]"
    if [ -n "$WORKER_IPS" ]; then
        workers_py="["
        local primero=1
        for ip in $WORKER_IPS; do
            if [ $primero -eq 0 ]; then
                workers_py="$workers_py, "
            fi
            workers_py="$workers_py\"$ip\""
            primero=0
        done
        workers_py="$workers_py]"
    fi

    cat > "$destino" <<EOF
# ══════════════════════════════════════════════════════════════
#  config.local.py — Configuración del Panel I2E
#  Generado automáticamente por scripts/instalacion.sh
#  Fecha: $(date -Iseconds)
# ══════════════════════════════════════════════════════════════
#
#  Este archivo personaliza el panel para un clúster específico.
#  No se versiona en git (está en .gitignore).
#  Después de modificarlo, reinicie el servicio:
#      sudo systemctl restart panel-i2e
# ══════════════════════════════════════════════════════════════

# ─── Nodos del clúster ────────────────────────────────────────
MANAGER_IP   = "$MANAGER_IP"
WORKER_IPS   = $workers_py
NAS_IP       = "$NAS_IP"

# ─── Rutas en el servidor ─────────────────────────────────────
ANSIBLE_DIR  = "$ANSIBLE_DIR"
NAS_BASE     = "$NAS_BASE"
MAC_SCRIPT   = "$HOME/Mac/Mac.sh"

# ─── Panel ────────────────────────────────────────────────────
PORT_PANEL   = $PANEL_PORT
SSH_USER     = "$PANEL_USER"

# ─── Cuenta inicial de administrador ──────────────────────────
ADMIN_USER     = "$ADMIN_USER"
ADMIN_PASSWORD = "$ADMIN_PASSWORD"

# ─── Límite de subida al NAS (MB) ─────────────────────────────
NAS_MAX_UPLOAD_MB = 2048

# ─── Puertos de las aplicaciones del clúster ──────────────────
PORT_JUPYTER    = 8888
PORT_SPARK_UI   = 8080
PORT_SPARK      = 7077
PORT_RAY_DASH   = 8265
PORT_RAY        = 6380
PORT_PORTAINER  = 9443
PORT_TTYD       = 7681
EOF

    chmod 600 "$destino"
    msg_ok "Archivo generado: $destino"
}

# ────────────────────────────────────────────────────────────────
# 6. Generación de .env
# ────────────────────────────────────────────────────────────────
generar_env() {
    msg_seccion "Archivo de variables de entorno"

    local destino="$PROYECTO_DIR/.env"

    if [ -f "$destino" ]; then
        msg_ok "$destino ya existe, se conserva"
        return 0
    fi

    local secret
    secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

    cat > "$destino" <<EOF
PANEL_SECRET_KEY=$secret
EOF
    chmod 600 "$destino"
    msg_ok "Archivo generado: $destino (modo 600)"
}

# ────────────────────────────────────────────────────────────────
# 7. Entorno virtual
# ────────────────────────────────────────────────────────────────
crear_venv() {
    msg_seccion "Entorno virtual de Python"

    local venv="$PROYECTO_DIR/venv"

    if [ ! -d "$venv" ]; then
        msg_info "Creando entorno virtual en $venv"
        python3 -m venv "$venv"
    else
        msg_ok "El entorno virtual ya existe"
    fi

    msg_info "Actualizando pip"
    "$venv/bin/pip" install --quiet --upgrade pip

    msg_info "Instalando dependencias desde requirements.txt"
    "$venv/bin/pip" install --quiet -r "$PROYECTO_DIR/requirements.txt"

    msg_ok "Dependencias instaladas"
}

# ────────────────────────────────────────────────────────────────
# 8. Claves SSH del panel
# ────────────────────────────────────────────────────────────────
generar_claves() {
    msg_seccion "Claves SSH del panel"

    local priv="$PROYECTO_DIR/data/ssh_panel_key"
    local pub="$PROYECTO_DIR/data/ssh_panel_key.pub"
    local master="$PROYECTO_DIR/data/master.key"

    if [ ! -f "$priv" ]; then
        msg_info "Generando clave SSH dedicada del panel"
        ssh-keygen -t ed25519 -N "" -f "$priv" -C "panel-i2e@$(hostname)" >/dev/null
    fi

    chmod 600 "$priv"
    chmod 644 "$pub"
    msg_ok "Clave SSH del panel lista"

    if [ ! -f "$master" ]; then
        msg_info "Generando clave maestra de cifrado de credenciales"
        python3 -c "from cryptography.fernet import Fernet; \
                    open('$master','wb').write(Fernet.generate_key())"
    fi
    chmod 600 "$master"
    msg_ok "Clave maestra lista"
}

# ────────────────────────────────────────────────────────────────
# 9. Servicio systemd
# ────────────────────────────────────────────────────────────────
instalar_servicio() {
    msg_seccion "Servicio del sistema"

    local unit="/etc/systemd/system/panel-i2e.service"

    if [ -f "$unit" ]; then
        msg_warn "$unit ya existe"
        if ! preguntar_sn "¿Reemplazar por la nueva configuración?" "s"; then
            msg_info "Se conserva el servicio existente."
            return 0
        fi
    fi

    sudo tee "$unit" > /dev/null <<EOF
[Unit]
Description=Panel de Control I2E (Flask + gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$PANEL_USER
Group=$PANEL_USER
WorkingDirectory=$PROYECTO_DIR

EnvironmentFile=$PROYECTO_DIR/.env
Environment="PATH=$PROYECTO_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="HOME=/home/$PANEL_USER"
Environment="PYTHONUNBUFFERED=1"

ExecStart=$PROYECTO_DIR/venv/bin/gunicorn \\
  --workers 1 \\
  --worker-class gthread \\
  --threads 16 \\
  --bind 0.0.0.0:$PANEL_PORT \\
  --timeout 300 \\
  --graceful-timeout 30 \\
  --access-logfile $PROYECTO_DIR/logs/access.log \\
  --error-logfile $PROYECTO_DIR/logs/error.log \\
  --chdir $PROYECTO_DIR \\
  wsgi:app

Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=false
ReadWritePaths=$PROYECTO_DIR

StandardOutput=journal
StandardError=journal
SyslogIdentifier=panel-i2e

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable panel-i2e >/dev/null 2>&1
    msg_ok "Servicio instalado y habilitado"
}

# ────────────────────────────────────────────────────────────────
# 10. Configuración de sudoers
# ────────────────────────────────────────────────────────────────
configurar_sudoers() {
    msg_seccion "Permisos de sudo"

    local archivo="/etc/sudoers.d/90-panel-i2e-$PANEL_USER"

    if [ -f "$archivo" ]; then
        msg_ok "Regla de sudoers ya existe: $archivo"
        return 0
    fi

    printf '%s ALL=(ALL) NOPASSWD: ALL\n' "$PANEL_USER" \
        | sudo tee "$archivo" >/dev/null

    sudo chmod 440 "$archivo"
    sudo chown root:root "$archivo"

    if sudo visudo -cf "$archivo" >/dev/null 2>&1; then
        msg_ok "Regla de sudoers creada: $archivo"
    else
        sudo rm -f "$archivo"
        abortar "La regla de sudoers no pasó la validación. Se ha eliminado."
    fi
}

# ────────────────────────────────────────────────────────────────
# 11. Arranque y verificación
# ────────────────────────────────────────────────────────────────
arrancar_verificar() {
    msg_seccion "Arranque del servicio"

    sudo systemctl restart panel-i2e
    sleep 3

    if ! systemctl is-active --quiet panel-i2e; then
        msg_err "El servicio no arrancó correctamente."
        printf '\nÚltimas líneas del registro:\n'
        sudo journalctl -u panel-i2e -n 30 --no-pager
        abortar "Revisar la salida anterior para diagnosticar el problema."
    fi

    msg_ok "El servicio está activo"

    # Verificar respuesta HTTP
    local intentos=0
    while [ $intentos -lt 10 ]; do
        if curl -sS -o /dev/null "http://127.0.0.1:$PANEL_PORT/api/health" 2>/dev/null; then
            msg_ok "El panel responde en http://127.0.0.1:$PANEL_PORT"
            return 0
        fi
        sleep 1
        intentos=$((intentos + 1))
    done

    msg_warn "El panel arrancó pero no responde en /api/health tras 10 segundos."
    msg_info "Verifique los registros con: sudo journalctl -u panel-i2e -n 50 --no-pager"
}

# ────────────────────────────────────────────────────────────────
# 12. Aplicaciones opcionales
# ────────────────────────────────────────────────────────────────
instalar_mlflow_opcional() {
    msg_seccion "Aplicación opcional: MLflow"

    printf 'MLflow es una plataforma para registrar y comparar experimentos\n'
    printf 'de aprendizaje automático. Se instala en /opt/mlflow y ocupa\n'
    printf 'aproximadamente 500 MB.\n\n'

    if ! preguntar_sn "¿Instalar MLflow ahora?" "n"; then
        msg_info "Omitido. Puede instalarlo después desde la pestaña Aplicaciones."
        return 0
    fi

    local opt="/opt/mlflow"

    if [ -d "$opt" ] && [ -x "$opt/venv/bin/mlflow" ]; then
        msg_ok "MLflow ya está instalado en $opt"
    else
        sudo mkdir -p "$opt"
        sudo chown "$PANEL_USER:$PANEL_USER" "$opt"

        msg_info "Creando entorno virtual"
        python3 -m venv "$opt/venv"
        "$opt/venv/bin/pip" install --quiet --upgrade pip
        msg_info "Instalando MLflow (puede tardar 2–3 minutos)"
        "$opt/venv/bin/pip" install --quiet mlflow
        msg_ok "MLflow instalado"
    fi

    # Servicio systemd
    local unit="/etc/systemd/system/mlflow.service"
    if [ ! -f "$unit" ]; then
        sudo tee "$unit" >/dev/null <<EOF
[Unit]
Description=MLflow Tracking Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$PANEL_USER
Group=$PANEL_USER
WorkingDirectory=$opt

ExecStart=$opt/venv/bin/mlflow server \\
  --host 0.0.0.0 \\
  --port 5000 \\
  --backend-store-uri sqlite:///$opt/mlflow.db \\
  --default-artifact-root $opt/artifacts \\
  --allowed-hosts "$MANAGER_IP:5000,$MANAGER_IP,localhost:5000,localhost,127.0.0.1:5000,127.0.0.1"

Restart=on-failure
RestartSec=5

StandardOutput=journal
StandardError=journal
SyslogIdentifier=mlflow

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable mlflow >/dev/null 2>&1
        msg_ok "Servicio MLflow instalado"
    fi

    sudo systemctl start mlflow
    sleep 12

    if systemctl is-active --quiet mlflow; then
        msg_ok "MLflow activo en http://$MANAGER_IP:5000"
    else
        msg_warn "MLflow no arrancó. Verifique con: sudo journalctl -u mlflow -n 40"
    fi

    # Añadir al JSON de apps si no está
    local apps_json="$PROYECTO_DIR/data/apps.json"
    if [ -f "$apps_json" ]; then
        if ! grep -q '"id": "mlflow"' "$apps_json" 2>/dev/null; then
            msg_info "Añada la aplicación desde el panel:"
            printf '  Nombre: MLflow\n'
            printf '  Host:   %s\n' "$MANAGER_IP"
            printf '  Puerto: 5000\n'
            printf '  Chequeo URL: /\n'
            printf '  Iniciar systemd: mlflow\n'
            printf '  Detener systemd: mlflow\n'
        fi
    fi
}

# ────────────────────────────────────────────────────────────────
# 13. Resumen final
# ────────────────────────────────────────────────────────────────
mostrar_resumen() {
    msg_seccion "Instalación finalizada"

    cat <<EOF

El panel está operativo.

  URL del panel:      http://$MANAGER_IP:$PANEL_PORT
  Usuario inicial:    $ADMIN_USER
  Servicio systemd:   panel-i2e

Comandos útiles:

  sudo systemctl status panel-i2e      Ver el estado del servicio
  sudo systemctl restart panel-i2e     Reiniciar el panel
  sudo journalctl -u panel-i2e -f      Ver los registros en tiempo real
  cat $PROYECTO_DIR/logs/error.log      Ver el registro de errores

Pasos siguientes recomendados:

  1. Acceda al panel con las credenciales configuradas.
  2. Configure los nodos en la pestaña Estado.
  3. Distribuya la clave SSH del panel a los nodos worker
     (se realiza automáticamente al abrir el terminal por primera vez).
  4. Aplique los playbooks de Ansible para preparar el clúster.
  5. Añada aplicaciones desde la pestaña Aplicaciones.

Documentación adicional en:

  README.md          Visión general del proyecto
  INSTALL.md         Instalación detallada
  CONFIGURATION.md   Opciones de configuración
  APPLICATIONS.md    Cómo añadir aplicaciones

EOF

    msg_ok "Instalación completada"
}

# ────────────────────────────────────────────────────────────────
# Flujo principal
# ────────────────────────────────────────────────────────────────
main() {
    mostrar_banner
    validar_contexto
    recoger_datos
    verificar_dependencias
    crear_estructura
    generar_config_local
    generar_env
    crear_venv
    generar_claves
    instalar_servicio
    configurar_sudoers
    arrancar_verificar
    instalar_mlflow_opcional
    mostrar_resumen
}

main "$@"
