#!/usr/bin/env python3
"""
Entry point del Cluster Panel I2E.

Uso:
    python run.py           # desarrollo
    gunicorn run:app        # producción
"""
import os
import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path
RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from core import create_app, main, app as _app

# Exponer la app para gunicorn: `gunicorn run:app`
app = _app


if __name__ == "__main__":
    main()
