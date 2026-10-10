# Panel de Control I2E

Panel web para administrar un clúster de cómputo Linux.

**Autores:** Jhonathan Dubernet Barón · Jenny Amparo Rosales Agredo · Fabián Rolando Jiménez López
**Institución:** Universidad Pedagógica y Tecnológica de Colombia (UPTC) — Facultad de Ingeniería, Escuela de Ingeniería Electrónica
**Año:** 2026

---

## ¿Qué hace?

- 📊 **Monitoreo del clúster**: CPU, RAM y disco de cada nodo en tiempo real
- 🖥️ **Terminal remota**: comandos puntuales + shell interactiva con PTY (vim, nano, htop)
- 👥 **Gestión de usuarios**: creación sincronizada entre YAML, sistema, NAS y credenciales
- 📦 **Navegador NAS**: subir, descargar, mover, previsualizar archivos
- ⚙️ **Playbooks Ansible**: editor, ejecución async, backups automáticos
- 🗂️ **Editor de inventario**: gestión del archivo `hosts` de Ansible
- ⚡ **Control de energía**: Wake-on-LAN, reinicio y apagado ordenado
- 🚀 **Aplicaciones**: control de Spark, Ray, JupyterHub, Portainer
- 🔐 **Auditoría**: registro inmutable de todas las acciones

## Stack

- **Backend:** Python 3.10+ · Flask 3 · Gunicorn · Ansible
- **Frontend:** HTML5 · CSS3 · JavaScript vanilla · xterm.js
- **Seguridad:** CSRF · Fernet (AES-128) · PAM · rate limiting

## Requisitos del clúster

- 1 nodo manager + N workers + 1 NAS en la misma red
- Ubuntu 22.04+ en todos los nodos
- SSH sin contraseña del manager hacia los nodos
- Ansible core 2.15+
- NFS para el NAS compartido

## Instalación rápida

Ver [INSTALL.md](./INSTALL.md).

## Documentación

- [INSTALL.md](./INSTALL.md) — Instalación paso a paso
- [CONFIGURATION.md](./CONFIGURATION.md) — Todas las opciones de configuración
- [ARCHITECTURE.md](./ARCHITECTURE.md) — Arquitectura y módulos
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) — Solución de problemas

## Licencia

Software de uso exclusivo del clúster I2E de la UPTC.
Ver [LICENSE](./LICENSE).

## Contacto

- jhonathan.baron@uptc.edu.co
- jenny.rosales@uptc.edu.co
- fabian.jimenez02@uptc.edu.co
