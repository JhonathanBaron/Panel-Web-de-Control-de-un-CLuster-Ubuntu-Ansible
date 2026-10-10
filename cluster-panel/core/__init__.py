"""
Cluster Panel I2E — Paquete principal.

Uso:
    from core import create_app
    app = create_app()
"""
from .app import create_app, app, main

__all__ = ["create_app", "app", "main"]
