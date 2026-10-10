#!/usr/bin/env python3
"""
Resetea la contraseña de un usuario del panel.

Uso:
    python3 reset-password.py                      # resetea el admin por defecto
    python3 reset-password.py ana.perez            # resetea un usuario específico
    python3 reset-password.py ana.perez mipass123  # resetea con contraseña específica
"""
import sys
import getpass
from credentials import listar_usuarios, cambiar_password, crear_usuario, verificar

def main():
    usuarios = listar_usuarios()

    if not usuarios:
        print("⚠️  No hay usuarios creados.")
        print("Creando admin por defecto: Cluster0 / oxoCluster0")
        from credentials import init_default_admin
        init_default_admin()
        print("✅ Admin creado: Cluster0 / oxoCluster0")
        return

    print("Usuarios disponibles:")
    for u, info in usuarios.items():
        print(f"  · {u} ({info.get('role')})")
    print()

    if len(sys.argv) > 1:
        usuario = sys.argv[1]
    else:
        usuario = input("¿Qué usuario quieres resetear? [Cluster0]: ").strip() or "Cluster0"

    if usuario not in usuarios:
        print(f"❌ Usuario '{usuario}' no existe.")
        sys.exit(1)

    if len(sys.argv) > 2:
        nueva = sys.argv[2]
    else:
        nueva = getpass.getpass(f"Nueva contraseña para {usuario}: ")
        confirmar = getpass.getpass("Confirma la nueva contraseña: ")
        if nueva != confirmar:
            print("❌ Las contraseñas no coinciden.")
            sys.exit(1)

    if len(nueva) < 8:
        print("❌ La contraseña debe tener mínimo 8 caracteres.")
        sys.exit(1)

    if cambiar_password(usuario, nueva):
        print(f"✅ Contraseña de '{usuario}' actualizada.")
        print(f"   Puedes iniciar sesión en el panel con esa contraseña.")
    else:
        print(f"❌ Error al cambiar la contraseña de '{usuario}'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
