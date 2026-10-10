# Guia de Instalacion Completa del Cluster I2E

Esta guia describe, paso a paso, como reproducir el cluster de computo Beowulf del **Semillero MATRIS2** desde cero. 

## NOTA: Las direcciones ip se ajustan de acuerdo a tu red; se tomo de manera general 192.168.1.X, como ejemplo.

## Indice

1. Requisitos previos
2. Arquitectura del cluster
3. Preparacion de los equipos
4. Configuracion de red
5. Configuracion de SSH
6. Instalacion de Ansible
7. Configuracion del NAS
8. Instalacion del servidor LDAP
9. Aprovisionamiento con playbooks
10. Instalacion de las aplicaciones
11. Despliegue de los paneles web
12. Verificacion final

---

## 1. Requisitos previos

### Hardware

- 10 equipos tipo desktop o SFF con:
  - Procesador Intel Core i5 o superior (minimo 4 nucleos)
  - RAM: 8 GB minimo (16 GB recomendado para nodos heavy)
  - Disco: 256 GB minimo
  - Tarjeta de red gigabit
- 1 switch gigabit para la red interna
- 1 tarjeta Arduino + 4 ventiladores PWM + 1 rele (control termico)
- 1 servidor NAS

### Software

- Ubuntu 22.04.5 LTS en todos los nodos (Server Edition)
- Conexion a Internet durante la instalacion

---

## 2. Arquitectura del cluster

| Nodo | IP (ejemplo) | Rol | Grupo Ansible |
|------|--------------|-----|---------------|
| Manager | 192.168.1.10 | Administrador | manager |
| Worker 1 | 192.168.1.11 | Computo | light |
| Worker 2 | 192.168.1.12 | Computo | light |
| Worker 3 | 192.168.1.13 | Computo | heavy |
| Worker 4 | 192.168.1.14 | Computo | light |
| Worker 5 | 192.168.1.15 | Computo | light |
| Worker 6 | 192.168.1.16 | Computo | heavy |
| Worker 7 | 192.168.1.17 | Computo | heavy |
| Worker 8 | 192.168.1.18 | Computo | heavy |
| NAS | 192.168.1.19 | Almacenamiento | nas |

Red interna: 192.168.1.0/24

> Nota: en el laboratorio I2E real se usa 10.4.8.0/24. Ajustar segun tu entorno.

---

## 3. Preparacion de los equipos

### Instalar Ubuntu 22.04.5 LTS

En cada equipo instalar Ubuntu Server 22.04.5 LTS con:
- Usuario: cluster0 (manager), cluster1 a cluster8 (workers), cluster9 (NAS)
- Marcar OpenSSH Server
- Instalacion minima

### Actualizar

En cada nodo:

    sudo apt update && sudo apt upgrade -y
    sudo apt install -y curl git vim htop net-tools

---

## 4. Configuracion de red

Editar /etc/netplan/00-installer-config.yaml:

    network:
      version: 2
      ethernets:
        enp3s0:
          dhcp4: false
          addresses:
            - 192.168.1.10/24
          gateway4: 192.168.1.1
          nameservers:
            addresses: [8.8.8.8, 1.1.1.1]

Aplicar:

    sudo netplan apply

---

## 5. Configuracion de SSH

En el manager:

    ssh-keygen -t ed25519 -C "cluster@i2e" -f ~/.ssh/id_ed25519 -N ""

Copiar la clave a cada nodo:

    ssh-copy-id cluster1@192.168.1.11
    ssh-copy-id cluster2@192.168.1.12
    # ... hasta cluster8@192.168.1.18
    ssh-copy-id cluster9@192.168.1.19

Verificar:

    ssh cluster1@192.168.1.11 hostname

---

## 6. Instalacion de Ansible

En el manager:

    sudo apt install -y ansible
    ansible --version

Crear estructura:

    mkdir -p ~/cluster-i2e/{playbooks,users,group_vars,host_vars}
    cp /ruta/del/repo/cluster-i2e-example/hosts.example ~/cluster-i2e/hosts
    cp /ruta/del/repo/cluster-i2e-example/playbooks/*.yml ~/cluster-i2e/playbooks/
    nano ~/cluster-i2e/hosts

Probar:

    cd ~/cluster-i2e
    ansible all -i hosts -m ping

---

## 7. Configuracion del NAS

Ver documento 03_CONFIGURACION_NAS.md.

Resumen:
1. En el NAS: instalar nfs-kernel-server, exportar /srv/nas
2. En cada nodo: instalar nfs-common, montar 192.168.1.19:/srv/nas
3. Configurar quotas por usuario
4. Automatizar con playbooks 04_home_mount.yml

---

## 8. Instalacion del servidor LDAP

    ansible-playbook -i hosts playbooks/01_ldap_server.yml
    ansible-playbook -i hosts playbooks/02_ldap_clients.yml

---

## 9. Aprovisionamiento con playbooks

    cd ~/cluster-i2e

    ansible-playbook -i hosts playbooks/00_base.yml
    ansible-playbook -i hosts playbooks/10_base_dev.yml
    ansible-playbook -i hosts playbooks/02_docker.yml
    ansible-playbook -i hosts playbooks/16_apptainer.yml
    ansible-playbook -i hosts playbooks/11_python_science.yml
    ansible-playbook -i hosts playbooks/12_miniforge.yml
    ansible-playbook -i hosts playbooks/13_ml_stack.yml
    ansible-playbook -i hosts playbooks/14_parallel_stack.yml
    ansible-playbook -i hosts playbooks/15_security_net.yml
    ansible-playbook -i hosts playbooks/20_users.yml
    ansible-playbook -i hosts playbooks/21_kernels.yml
    ansible-playbook -i hosts playbooks/21_student_restrictions.yml

    ansible-playbook -i hosts playbooks/01_nas_prep.yml
    ansible-playbook -i hosts playbooks/03_nas_quotas.yml
    ansible-playbook -i hosts playbooks/04_home_mount.yml

---

## 10. Instalacion de las aplicaciones

    ansible-playbook -i hosts playbooks/17_jupyterhub.yml
    ansible-playbook -i hosts playbooks/18_ray.yml
    ansible-playbook -i hosts playbooks/19_spark.yml
    ansible-playbook -i hosts playbooks/03_portainer.yml

---

## 11. Despliegue de los paneles web

    cd ~
    git clone git@github.com:JhonathanBaron/Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible.git
    cd Panel-Web-de-Control-de-un-CLuster-Ubuntu-Ansible

    cd panel-i2e
    bash INSTALACION.sh
    sudo systemctl enable --now panel-i2e

    cd ../cluster-panel
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    nano .env

---

## 12. Verificacion final

    sudo systemctl status panel-i2e
    sudo systemctl status cluster-panel
    ansible all -i ~/cluster-i2e/hosts -m ping

Acceso a los paneles:
- http://192.168.1.10:7000  (Panel de Control)
- http://192.168.1.10:8080  (Panel Termico)
