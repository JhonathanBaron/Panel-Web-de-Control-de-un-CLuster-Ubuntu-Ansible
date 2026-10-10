import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


class Config:
    # Flask
    PANEL_PORT = int(os.environ.get("PANEL_PORT", "9000"))
    PANEL_HOST = os.environ.get("PANEL_HOST", "0.0.0.0")
    SECRET_KEY = os.environ.get("PANEL_SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATA_DIR/'panel.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 3600 * 8

    # Ansible
    ANSIBLE_BIN       = "/usr/bin/ansible"
    ANSIBLE_INVENTORY = os.environ.get(
        "ANSIBLE_INVENTORY", str(Path.home() / "cluster-i2e" / "hosts"))
    ANSIBLE_CWD       = os.environ.get(
        "ANSIBLE_CWD", str(Path.home() / "cluster-i2e"))
    ANSIBLE_TIMEOUT   = 60

    # Arduino
    ARDUINO_PORT = os.environ.get("ARDUINO_PORT", "/dev/ttyUSB0")
    ARDUINO_BAUD = int(os.environ.get("ARDUINO_BAUD", "9600"))
    ARDUINO_RETRY_DELAY = 30

    # Muestreo
    SAMPLE_INTERVAL = int(os.environ.get("SAMPLE_INTERVAL", "10"))
    DETAIL_TIMEOUT  = 20

    # Retención
    RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))

    # Umbrales
    TEMP_WARNING  = 60.0
    TEMP_CRITICAL = 75.0
    CPU_WARNING   = 85.0
    RAM_WARNING   = 90.0
    DISK_WARNING  = 85.0

    # Curva ventiladores
    FAN_MIN_TEMP = 40.0
    FAN_MAX_TEMP = 75.0
