# Configuracion del NAS Compartido

El cluster usa un servidor NAS (Network Attached Storage) que exporta un directorio compartido a todos los nodos via NFS.

## Arquitectura

- Servidor NAS: 192.168.1.19
- Directorio exportado: /srv/nas
- Cliente NFS: todos los nodos montan /srv/nas en la misma ruta

## Estructura de directorios

    /srv/nas/
    +-- home/                 Home compartido
    |   +-- profesor.ejemplo/
    |   +-- estudiante.ejemplo/
    +-- shared/               Espacio compartido

## Paso 1: Configurar el servidor NAS

En 192.168.1.19:

    sudo apt update
    sudo apt install -y nfs-kernel-server

    sudo mkdir -p /srv/nas/home
    sudo mkdir -p /srv/nas/shared

    sudo chown -R nobody:nogroup /srv/nas
    sudo chmod -R 755 /srv/nas

    echo "/srv/nas 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports

    sudo exportfs -ra
    sudo systemctl enable --now nfs-kernel-server

Verificar:

    sudo exportfs -v

## Paso 2: Configurar los clientes NFS

En cada nodo (excepto el NAS):

    sudo apt install -y nfs-common
    sudo mkdir -p /srv/nas
    sudo mount -t nfs 192.168.1.19:/srv/nas /srv/nas

Montaje automatico en /etc/fstab:

    192.168.1.19:/srv/nas  /srv/nas  nfs  defaults,_netdev,noatime  0  0

Probar:

    sudo mount -a
    df -h | grep nas

## Paso 3: Automatizar con Ansible

    cd ~/cluster-i2e
    ansible-playbook -i hosts playbooks/04_nas_mount_only.yml
    ansible-playbook -i hosts playbooks/04_home_mount.yml

## Paso 4: Quotas por usuario

    ansible-playbook -i hosts playbooks/03_nas_quotas.yml

## Solucion de problemas

- "Permission denied": verificar no_root_squash en /etc/exports
- El montaje no persiste: revisar /etc/fstab y opcion _netdev
- "access denied by server": verificar IP del cliente en el rango permitido