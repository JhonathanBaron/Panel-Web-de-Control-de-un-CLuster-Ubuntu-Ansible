# data/ — Datos en runtime

Este directorio se genera automáticamente al arrancar el panel.
NO se sube al repo (excepto este README).

## Contenido esperado

| Archivo/carpeta         | Qué es                                  | ¿Se sube a git? |
|-------------------------|-----------------------------------------|-----------------|
| `master.key`            | Clave Fernet (chmod 600)                | ❌ NO           |
| `credentials.enc`       | Credenciales del panel (cifradas)       | ❌ NO           |
| `nodes.json`            | Config de MAC/WOL por nodo              | ❌ NO           |
| `audit.jsonl`           | Log de auditoría                        | ❌ NO           |
| `metrics.jsonl`         | Histórico de métricas                   | ❌ NO           |
| `tasks/`                | Tareas en background persistidas        | ❌ NO           |
| `inventory-backups/`    | Backups del archivo `hosts` de Ansible  | ❌ NO           |
| `playbooks-backup/`     | Backups de playbooks                    | ❌ NO           |

## Regenerar

Si borras `data/`, al reiniciar el panel se regeneran automáticamente:

- `master.key` → se genera con `Fernet.generate_key()`
- `credentials.enc` → se crea vacío (usa `reset-password.py` para el admin)
- `nodes.json` → se crea vacío
- `audit.jsonl` y `metrics.jsonl` → se crean vacíos
- `tasks/` → se crea vacío

⚠ Guarda un backup de `data/` si tienes usuarios y MACs configurados.
