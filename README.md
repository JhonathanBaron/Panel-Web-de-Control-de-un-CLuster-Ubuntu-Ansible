
# Panel Web de Control de un Clúster Ubuntu + Ansible

Conjunto de aplicaciones web para la administración y el monitoreo del clúster Beowulf del **Semillero MATRIS2** (grupo de investigación I²E, Escuela de Ingeniería Electrónica, Universidad Pedagógica y Tecnológica de Colombia).

## Componentes

### 1. Panel de Control Principal — `panel-i2e/`

- Monitoreo en tiempo real de CPU, RAM y disco de cada nodo
- Gestión de usuarios sincronizada con Ansible, NAS y credenciales
- Terminal remota con soporte PTY (vim, nano, htop)
- Navegador del almacenamiento compartido (NAS)
- Editor de playbooks de Ansible
- Gestión del inventario
- Control de energía (Wake-on-LAN, reinicio, apagado)
- Control de aplicaciones (Spark, Ray, JupyterHub, Portainer)
- Auditoría inmutable de acciones

**Puerto por defecto:** 7000

### 2. Panel de Análisis Térmico — `cluster-panel/`

- Monitoreo continuo de temperatura, CPU, RAM y disco
- Control automático de ventiladores vía Arduino (4 PWM + 1 relé)
- Curva de interpolación cuadrática (40 °C ↔ 75 °C)
- Análisis temporal con gráficas interactivas
- Histórico persistente en SQLite
- Registro de eventos filtrable y exportable

**Puerto por defecto:** 8080

## Arquitectura del clúster

| Nodo | IP | Rol |
|------|----|----|
| Manager | 10.4.8.10 | Nodo administrador (ejecuta ambos paneles) |
| Workers | 10.4.8.11 – 10.4.8.18 | Nodos de cómputo |
| NAS | 10.4.8.19 | Servidor de almacenamiento compartido |

- **Red interna:** 10.4.8.0/24 (sin DNS, acceso por IP)
- **Sistema operativo:** Ubuntu 22.04.5 LTS
- **Acceso:** red local del laboratorio o VPN institucional (no expuesto a Internet)

## Stack técnico

**Panel de Control Principal:**
- Python 3.10+ / Flask 3.0 / Gunicorn
- flask-sock (WebSocket para terminal PTY)
- Ansible core 2.15+
- xterm.js 5.5.0

**Panel de Análisis Térmico:**
- Python 3.10+ / Flask
- SQLAlchemy + SQLite
- pyserial (Arduino)

## Autores

- Jhonathan Duberney Barón Hernández
- Jenny Amparo Rosales Agredo
- Fabián Rolando Jiménez López

## Institución

Universidad Pedagógica y Tecnológica de Colombia (UPTC)
Facultad de Ingeniería — Escuela de Ingeniería Electrónica
Semillero MATRIS2 — Grupo de Investigación I²E
Tunja, Colombia — 2026

## Licencia

Software de uso exclusivo del Semillero MATRIS2 y del grupo de investigación I²E de la UPTC.

## Contacto

- jhonathan.baron@uptc.edu.co
- jenny.rosales@uptc.edu.co
- fabian.jimenez02@uptc.edu.co