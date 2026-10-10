import re
import json


def validar_ip(ip):
    import ipaddress
    try:
        ipaddress.ip_address(ip)
        return True
    except (ValueError, TypeError):
        return False


def validar_mac(mac):
    return bool(re.fullmatch(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac or ""))


def parsear_cpu(linea):
    def match(pat):
        m = re.search(pat, linea)
        return float(m.group(1).replace(',', '.')) if m else 0.0
    return match(r'(\d+[,.]?\d*)\s*us') + \
           match(r'(\d+[,.]?\d*)\s*sy') + \
           match(r'(\d+[,.]?\d*)\s*ni')


def parsear_linea_salida(linea):
    if '|' not in linea:
        return None
    partes = linea.split('|')
    if len(partes) < 6:
        return None
    try:
        return {
            "temp":      int(partes[0]) / 1000.0 if partes[0].isdigit() else 0.0,
            "cpu":       float(partes[1].replace(',', '.')) if partes[1] else 0.0,
            "ram_used":  int(partes[2]) if partes[2].isdigit() else 0,
            "ram_total": int(partes[3]) if partes[3].isdigit() else 0,
            "disk_pct":  float(partes[4]) if partes[4] else 0.0,
            "load1":     float(partes[5].replace(',', '.')) if partes[5] else 0.0,
        }
    except (ValueError, IndexError):
        return None


COMANDO_SAMPLE = r"""
TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
CPU_LINE=$(top -bn1 | grep '%Cpu' | head -1)
CPU_US=$(echo "$CPU_LINE" | awk '{print $2}' | sed 's/,/./;s/%//')
CPU_SY=$(echo "$CPU_LINE" | awk '{print $4}' | sed 's/,/./;s/%//')
CPU_NI=$(echo "$CPU_LINE" | awk '{print $6}' | sed 's/,/./;s/%//')
CPU=$(awk "BEGIN{printf \"%.1f\", ${CPU_US:-0} + ${CPU_SY:-0} + ${CPU_NI:-0}}")
RAM=$(free -m | awk '/^Mem:/ {print $3"|"$2}')
DISK=$(df / | awk 'NR==2 {gsub("%",""); print $5}')
LOAD=$(cat /proc/loadavg | awk '{print $1}')
echo "${TEMP}|${CPU}|${RAM}|${DISK}|${LOAD}"
""".strip()


def log_event(level, category, message, node_ip=None, meta=None):
    from .extensions import db
    from .models import EventLog
    try:
        db.session.add(EventLog(
            level=level, category=category, message=message,
            node_ip=node_ip,
            meta=json.dumps(meta) if meta else None,
        ))
        db.session.commit()
    except Exception as e:
        print(f"[log_event] error: {e}")
