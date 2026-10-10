#!/bin/bash
# ============================================================
# setup_manager.sh
# Configura el nodo manager del cluster I2E
# ============================================================
set -e

echo "=== Configurando manager del cluster I2E ==="

# Verificar que es Ubuntu
if [ ! -f /etc/os-release ]; then
    echo "ERROR: no es un sistema compatible"
    exit 1
fi

# Instalar dependencias
echo "-> Instalando dependencias base..."
sudo apt update
sudo apt install -y \
    python3 python3-pip python3-venv \
    ansible git curl wget \
    nfs-common \
    vim htop tmux

# Instalar Ansible
echo "-> Verificando Ansible..."
ansible --version

# Crear estructura de ~/cluster-i2e
echo "-> Creando estructura del proyecto Ansible..."
mkdir -p ~/cluster-i2e/{playbooks,users,group_vars,host_vars}

# Generar claves SSH si no existen
if [ ! -f ~/.ssh/id_ed25519 ]; then
    echo "-> Generando clave SSH..."
    ssh-keygen -t ed25519 -C "cluster@i2e" -f ~/.ssh/id_ed25519 -N ""
fi

echo ""
echo "=== Manager configurado ==="
echo ""
echo "Pasos siguientes:"
echo "1. Editar ~/cluster-i2e/hosts con las IPs reales"
echo "2. Copiar las claves SSH a todos los nodos:"
echo "     ssh-copy-id cluster1@192.168.1.11"
echo "     # ... para cada worker"
echo "3. Verificar conectividad:"
echo "     cd ~/cluster-i2e && ansible all -m ping"
echo "4. Ejecutar los playbooks en orden:"
echo "     ansible-playbook playbooks/00_base.yml"