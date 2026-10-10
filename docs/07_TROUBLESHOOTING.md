# Solucion de Problemas

Guia de diagnostico y solucion para los problemas mas comunes.

## Ansible

### Error: Permission denied (publickey)

Verificar claves SSH:

    ssh -T cluster1@192.168.1.11
    ssh-copy-id cluster1@192.168.1.11

### Error: Host key verification failed

Limpiar la clave conocida:

    ssh-keygen -R 192.168.1.11

### Error: Become password required

Configurar sudo sin password para el usuario `cluster*`:

    echo "cluster1 ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/cluster1

O descomentar `ansible_become_pass` en el inventario.

---

## NAS

### El montaje NFS no persiste tras reinicio

Verificar /etc/fstab:

    192.168.1.19:/srv/nas /srv/nas nfs defaults,_netdev,noatime 0 0

La opcion `_netdev` es critica.

### Permission denied al escribir

Verificar en el servidor NAS:

    sudo exportfs -v
    cat /etc/exports

Debe incluir `no_root_squash`.

### El servidor NAS no responde

    # En el cliente
    showmount -e 192.168.1.19

    # En el servidor
    sudo systemctl status nfs-kernel-server

---

## LDAP

### Los usuarios no pueden iniciar sesion

Verificar /etc/ldap/ldap.conf apunta al servidor correcto:

    URI ldap://192.168.1.10
    BASE dc=i2e,dc=local

### Error "Invalid credentials"

Restablecer la contrasena del usuario:

    sudo ldappasswd -H ldap://localhost -x -D "cn=admin,dc=i2e,dc=local" -W -S "uid=username,ou=people,dc=i2e,dc=local"

---

## Panel de Control I2E

### El servicio no arranca

    sudo systemctl status panel-i2e
    sudo journalctl -u panel-i2e -n 100 --no-pager

### Error "Address already in use"

Verificar que el puerto 7000 este libre:

    sudo ss -tlnp | grep 7000

### Error 500 en alguna pagina

Revisar logs:

    tail -100 ~/panel-i2e/logs/error.log

### Sesion expira muy rapido

Ajustar en config.py:

    PERMANENT_SESSION_LIFETIME = 3600 * 8  # 8 horas

### La terminal interactiva no conecta

Verificar flask-sock y WebSocket:

    pip show flask-sock
    sudo ss -tlnp | grep 7000

---

## Panel de Analisis Termico

### El Arduino no comunica

Verificar puerto:

    ls -la /dev/ttyUSB*
    dmesg | tail -20

Anadir usuario al grupo dialout:

    sudo usermod -a -G dialout cluster0
    # Cerrar sesion y volver a entrar

### La base de datos esta muy grande

Verificar el tamano:

    ls -lh cluster-panel/data/*.db

La retencion por defecto es 30 dias. Ajustar en .env:

    RETENTION_DAYS=15

### Las graficas no cargan

Verificar que los datos se esten recolectando:

    sqlite3 cluster-panel/data/metrics.db "SELECT COUNT(*) FROM metrics;"

---

## Cluster en general

### Nodo no responde

    # Desde el manager
    ping 192.168.1.15
    ansible 192.168.1.15 -i ~/cluster-i2e/hosts -m ping

Si no responde:
- Verificar cable de red
- Verificar IP con `ip a`
- Reiniciar el nodo

### Los ventiladores no giran

Verificar:
1. Modo del sistema (debe ser automatico o manual, no off)
2. Conexion del Arduino al manager
3. Alimentacion del rele
4. Log del panel termico

### Temperatura alta persistente

    # Ver temperaturas de todos los nodos
    ansible cluster -i hosts -a "sensors"

Limpiar fisicamente los ventiladores y el polvo del gabinete.

---

## Contacto de soporte

- jhonathan.baron@uptc.edu.co
- jenny.rosales@uptc.edu.co
- fabian.jimenez02@uptc.edu.co