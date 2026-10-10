# Cluster Panel I2E

Panel de monitoreo y control térmico del clúster Beowulf del Laboratorio de Investigación I2E.

## Características

- Monitoreo en tiempo real de temperatura, CPU, RAM y disco de todos los nodos
- Control de ventiladores vía Arduino (4 PWM + 1 relé) con curva automática
- Análisis temporal con gráficas interactivas (1h / 6h / 24h / 7d / 30d)
- Estadísticas min/avg/max por métrica y nodo
- Log de eventos filtrable con exportación a CSV
- Gestión de nodos (añadir/editar/eliminar) desde la interfaz
- Consultas on-demand de procesos, discos y uptime por nodo
- Histórico persistente en SQLite con retención configurable

## Estructura

    cluster-panel/
    ├── run.py                 Entry point
    ├── core/                  Código Python
    │   ├── app.py             Flask app + rutas
    │   ├── collector.py       Hilo de recolección (Ansible)
    │   ├── arduino.py         Comunicación serial
    │   ├── models.py          Modelos SQLAlchemy
    │   ├── config.py          Configuración
    │   └── utils.py           Helpers
    ├── templates/             Jinja2 HTML
    ├── static/                CSS + JS
    ├── data/                  SQLite + backups
    └── logs/                  Logs de la aplicación

## Instalación

    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

## Uso

Desarrollo:

    python run.py

Producción (gunicorn):

    gunicorn -w 2 --threads 4 -b 0.0.0.0:8080 run:app

## Variables de entorno

| Variable            | Default                  | Descripción                        |
|---------------------|--------------------------|------------------------------------|
| PANEL_SECRET_KEY    | dev-only-change-me       | Clave de sesión                    |
| ANSIBLE_INVENTORY   | ~/cluster-i2e/hosts      | Ruta al inventario de Ansible      |
| ARDUINO_PORT        | /dev/ttyUSB0             | Puerto serial del Arduino          |
| SAMPLE_INTERVAL     | 10                       | Segundos entre muestreos           |
| RETENTION_DAYS      | 30                       | Días de retención de histórico     |

## Créditos

Laboratorio de Investigación I2E — Universidad Pedagógica y Tecnológica de Colombia.
