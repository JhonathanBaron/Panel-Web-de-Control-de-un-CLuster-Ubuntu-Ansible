# Gestion de Usuarios del Cluster

El cluster I2E gestiona sus usuarios de forma centralizada mediante tres mecanismos complementarios:

1. Archivo YAML de definicion (users.yaml)
2. Sistema operativo de cada nodo (a traves de Ansible)
3. Servidor LDAP (para autenticacion distribuida)

## Rangos de UID por rol

| Rol | Rango UID | Descripcion |
|-----|-----------|-------------|
| professor | 20000-29999 | Personal docente e investigadores |
| student | 30000-39999 | Estudiantes |
| guest | 40000-49999 | Invitados y visitantes |

## Estructura del archivo users.yaml

    users:
      - username: profesor.ejemplo
        fullname: Profesor Ejemplo
        uid: 20001
        role: professor
        active: true
        created: '2026-01-01'

      - username: estudiante.ejemplo
        fullname: Estudiante Ejemplo
        uid: 30001
        role: student
        active: true
        created: '2026-01-01'

    config:
      shell: /bin/bash
      home_base: /srv/nas/home
      default_quota_gb: 10

## Crear un usuario

### Opcion A - Manualmente (editar el YAML)

    cd ~/cluster-i2e
    nano users/users.yaml

Anadir el bloque del nuevo usuario y ejecutar:

    ansible-playbook -i hosts playbooks/20_users.yml

### Opcion B - Desde el panel web

1. Acceder al Panel de Control con rol admin
2. Ir a la seccion "Usuarios del cluster"
3. Clic en "Nuevo usuario"
4. Rellenar el formulario
5. El sistema se encarga de todo automaticamente

## Como funciona el playbook 20_users.yml

1. Lee `users/users.yaml`
2. Para cada usuario:
   - Crea el usuario en todos los nodos con el UID correcto
   - Asigna la contrasena inicial
   - Crea el home en `/srv/nas/home/<username>/`
   - Aplica quotas de disco
   - Configura el shell

## Eliminar un usuario

### Manualmente:

1. Eliminar del YAML
2. Ejecutar:

       ansible cluster -i hosts -b -m user -a "name=username state=absent"
       rm -rf /srv/nas/home/username/

### Desde el panel:

Ir a "Usuarios del cluster", buscar el usuario, clic en el icono de basura.

## Cambiar la contrasena de un usuario

    ansible cluster -i hosts -b -m shell -a "echo 'username:nuevapass' | chpasswd"

O desde el panel: "Usuarios del cluster" > icono de llave.

## Configuracion de LDAP

El cluster usa LDAP para centralizar la autenticacion. Ver:

    ansible-playbook -i hosts playbooks/01_ldap_server.yml
    ansible-playbook -i hosts playbooks/02_ldap_clients.yml

Parametros de LDAP en `group_vars/all.yml`:

    ldap_domain: i2e.local
    ldap_admin_password: "CAMBIAR_ESTA_PASSWORD"
    ldap_base_dn: "dc=i2e,dc=local"

## Restricciones para estudiantes

El playbook `21_student_restrictions.yml` aplica limites:

- Sin acceso sudo
- Sin instalacion de paquetes
- Limite de procesos
- Sin acceso a ciertos comandos sensibles

## Verificacion

    # Listar usuarios del sistema
    ansible cluster -i hosts -a "getent passwd | grep -E '^[a-z]' | awk -F: '$3 >= 20000 && $3 <= 49999'"

    # Ver un usuario especifico
    ansible cluster -i hosts -a "id estudiante.ejemplo"

    # Ver el home
    ls /srv/nas/home/