#!/bin/bash
# ============================================================
# setup_nas.sh
# Configura un nodo como servidor NAS (NFS)
# ============================================================
set -e

echo "=== Configurando servidor NAS ==="

# Parametros (ajustar segun entorno)
NAS_DIR="/srv/nas"
NAS_NET="192.168.1.0/24"

# Instalar NFS server
echo "-> Instalando nfs-kernel-server..."
sudo apt update
sudo apt install -y nfs-kernel-server

# Crear estructura
echo "-> Creando $NAS_DIR..."
sudo mkdir -p "$NAS_DIR/home"
sudo mkdir -p "$NAS_DIR/shared"

# Permisos
sudo chown -R nobody:nogroup "$NAS_DIR"
sudo chmod -R 755 "$NAS_DIR"

# Configurar exports
echo "-> Configurando /etc/exports..."
if ! grep -q "^$NAS_DIR" /etc/exports 2>/dev/null; then
    echo "$NAS_DIR $NAS_NET(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
fi

# Aplicar
sudo exportfs -ra
sudo systemctl enable --now nfs-kernel-server

# Verificar
echo ""
echo "=== NAS configurado ==="
echo ""
sudo exportfs -v

echo ""
echo "Pasos siguientes:"
echo "1. En cada nodo cliente, agregar a /etc/fstab:"
echo "     192.168.1.19:$NAS_DIR $NAS_DIR nfs defaults,_netdev,noatime 0 0"
echo "2. Montar con: sudo mount -a"