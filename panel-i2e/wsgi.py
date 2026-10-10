"""
Entry point para gunicorn:
    gunicorn --chdir /home/cluster0/panel-i2e wsgi:app
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app import app  # noqa: E402

__all__ = ["app"]
