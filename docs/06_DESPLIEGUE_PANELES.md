# Despliegue de los Paneles Web

El cluster I2E usa dos paneles web complementarios que se ejecutan en el nodo manager.

## Arquitectura

| Panel | Puerto | Directorio | Servicio systemd |
|-------|--------|------------|------------------|
| Panel de Control Principal | 7000 | panel-i2e/ | panel-i2e.service |
| Panel de Analisis Termico | 8080 | cluster-panel/ | cluster-panel.service |

---

## Parte 1: Panel de Control Principal

### Requisitos

- Ubuntu 22.04 LTS
- Python 3.10+
- Ansible instalado
- Acceso SSH a todos los nodos
- NFS montado en /srv/nas

### Instalacion

    # Clonar el repositorio
    cd ~
    git clone git@github.com:JhonathanBaron/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible.git
    cd Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible/panel-i2e

    # Instalar dependencias
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

    # Instalar como servicio
    sudo cp panel-i2e.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now panel-i2e

### Verificacion

    sudo systemctl status panel-i2e
    journalctl -u panel-i2e -n 50

### Acceso

http://192.168.1.10:7000

### Configuracion

Editar `config.py` o crear `config.local.py` con valores especificos:

    SECRET_KEY = "cambiar-esta-clave"
    ANSIBLE_DIR = "/home/cluster0/cluster-i2e"
    NAS_BASE = "/srv/nas/home"
    PORT_PANEL = 7000

---

## Parte 2: Panel de Analisis Termico

### Requisitos

- El manager con Python 3.10+
- Arduino conectado por USB (opcional para desarrollo)
- Puerto serial accesible

### Instalacion

    cd ~/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible/cluster-panel

    # Crear entorno virtual
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

    # Configuracion
    cp .env.example .env
    nano .env

### Configuracion .env

    PANEL_SECRET_KEY=cambiar-esta-clave
    ANSIBLE_INVENTORY=/home/cluster0/cluster-i2e/hosts
    ARDUINO_PORT=/dev/ttyUSB0
    SAMPLE_INTERVAL=10
    RETENTION_DAYS=30

### Servicio systemd

Crear `/etc/systemd/system/cluster-panel.service`:

    [Unit]
    Description=Cluster Panel - Analisis Termico I2E
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    User=cluster0
    Group=cluster0
    WorkingDirectory=/home/cluster0/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible/cluster-panel
    Environment="PATH=/home/cluster0/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible/cluster-panel/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    ExecStart=/home/cluster0/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible/cluster-panel/venv/bin/gunicorn -w 2 --threads 4 -b 0.0.0.0:8080 run:app
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target

Activar:

    sudo systemctl daemon-reload
    sudo systemctl enable --now cluster-panel

### Acceso

http://192.168.1.10:8080

---

## Configuracion del Arduino

### Hardware

- Arduino Uno o compatible
- 4 canales PWM (pines 3, 5, 6, 9)
- 1 rele en pin 7
- Cable USB al manager

### Cargar el firmware

Desde el IDE de Arduino o por linea de comandos:

    avrdude -p atmega328p -c arduino -P /dev/ttyUSB0 -b 115200 -U flash:w:firmware.hex

### Protocolo serial

| Comando | Accion |
|---------|--------|
| F1:0-255 | Velocidad ventilador 1 |
| F2:0-255 | Velocidad ventilador 2 |
| F3:0-255 | Velocidad ventilador 3 |
| F4:0-255 | Velocidad ventilador 4 |
| RELE:ON | Activar rele |
| RELE:OFF | Desactivar rele |

### Verificar el puerto

    ls -la /dev/ttyUSB*
    sudo usermod -a -G dialout cluster0

---

## Actualizacion

    cd ~/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible
    git pull
    cd panel-i2e && source venv/bin/activate && pip install -r requirements.txt
    sudo systemctl restart panel-i2e
    cd ../cluster-panel && source venv/bin/activate && pip install -r requirements.txt
    sudo systemctl restart cluster-panel