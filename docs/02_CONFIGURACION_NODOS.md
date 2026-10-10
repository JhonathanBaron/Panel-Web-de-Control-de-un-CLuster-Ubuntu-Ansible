# Configuracion de los Nodos del Cluster

Este documento describe como configurar el inventario de Ansible y los nodos del cluster.

## Estructura del inventario

El archivo `hosts` en `~/cluster-i2e/` define los grupos y las variables de los nodos.

### Ejemplo

    [manager]
    192.168.1.10 ansible_user=cluster0

    [compute]
    192.168.1.11 ansible_user=cluster1
    192.168.1.12 ansible_user=cluster2
    192.168.1.13 ansible_user=cluster3
    192.168.1.14 ansible_user=cluster4
    192.168.1.15 ansible_user=cluster5
    192.168.1.16 ansible_user=cluster6
    192.168.1.17 ansible_user=cluster7
    192.168.1.18 ansible_user=cluster8

    [heavy]
    192.168.1.13
    192.168.1.16
    192.168.1.17
    192.168.1.18

    [light]
    192.168.1.11
    192.168.1.12
    192.168.1.14
    192.168.1.15

    [nas]
    192.168.1.19 ansible_user=cluster9

    [cluster:children]
    manager
    compute

    [all:vars]
    ansible_ssh_private_key_file=/home/cluster0/.ssh/id_ed25519
    ansible_python_interpreter=/usr/bin/python3

## Descripcion de los grupos

| Grupo | Proposito |
|-------|-----------|
| manager | Nodo administrador. Ejecuta los paneles web. |
| compute | Todos los workers de computo. |
| heavy | Workers con 16 GB de RAM (alto rendimiento). |
| light | Workers con 8 GB de RAM. |
| nas | Servidor de almacenamiento compartido. |
| cluster | Grupo padre que agrupa manager + compute. |

## Anadir un nodo nuevo

1. Anadir el host al grupo correspondiente en `~/cluster-i2e/hosts`:

       192.168.1.20 ansible_user=cluster10

2. Anadirlo tambien a heavy o light segun su hardware.

3. Copiar la clave SSH del manager:

       ssh-copy-id cluster10@192.168.1.20

4. Verificar:

       ansible all -i ~/cluster-i2e/hosts -m ping

## Verificar el inventario

    # Vista de arbol
    ansible-inventory -i ~/cluster-i2e/hosts --graph

    # Verificar conectividad
    ansible all -i ~/cluster-i2e/hosts -m ping

    # Comando ad-hoc
    ansible compute -i ~/cluster-i2e/hosts -a "uptime"