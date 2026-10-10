from datetime import datetime
from .extensions import db


class Node(db.Model):
    __tablename__ = "nodes"
    id         = db.Column(db.Integer, primary_key=True)
    ip         = db.Column(db.String(45), unique=True, nullable=False, index=True)
    name       = db.Column(db.String(64))
    mac        = db.Column(db.String(17))
    group      = db.Column(db.String(32), default="workers")
    role       = db.Column(db.String(16), default="worker")
    enabled    = db.Column(db.Boolean, default=True, nullable=False)
    notes      = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "ip": self.ip, "name": self.name, "mac": self.mac,
            "group": self.group, "role": self.role, "enabled": self.enabled,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ThermalReading(db.Model):
    __tablename__ = "thermal_readings"
    id        = db.Column(db.Integer, primary_key=True)
    node_ip   = db.Column(db.String(45), nullable=False)
    temp      = db.Column(db.Float)
    cpu       = db.Column(db.Float)
    ram_used  = db.Column(db.Integer)
    ram_total = db.Column(db.Integer)
    disk_pct  = db.Column(db.Float)
    load1     = db.Column(db.Float)
    online    = db.Column(db.Boolean, default=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.Index('ix_thermal_node_ts', 'node_ip', 'timestamp'),)

    def to_dict(self):
        return {
            "node_ip": self.node_ip, "temp": self.temp, "cpu": self.cpu,
            "ram_used": self.ram_used, "ram_total": self.ram_total,
            "disk_pct": self.disk_pct, "load1": self.load1,
            "online": self.online,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class EventLog(db.Model):
    __tablename__ = "event_logs"
    id        = db.Column(db.Integer, primary_key=True)
    level     = db.Column(db.String(16))
    category  = db.Column(db.String(32))
    message   = db.Column(db.Text, nullable=False)
    node_ip   = db.Column(db.String(45))
    meta      = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "level": self.level, "category": self.category,
            "message": self.message, "node_ip": self.node_ip, "meta": self.meta,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class Setting(db.Model):
    __tablename__ = "settings"
    key   = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)

    @staticmethod
    def get(key, default=None):
        s = db.session.get(Setting, key)
        return s.value if s else default

    @staticmethod
    def set(key, value):
        s = db.session.get(Setting, key)
        if s:
            s.value = str(value)
        else:
            db.session.add(Setting(key=key, value=str(value)))
        db.session.commit()


class FanState(db.Model):
    __tablename__ = "fan_state"
    pin        = db.Column(db.String(4), primary_key=True)
    name       = db.Column(db.String(32))
    value      = db.Column(db.Integer, default=0)
    tipo       = db.Column(db.String(16), default="pwm")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def to_dict(self):
        return {"pin": self.pin, "name": self.name, "value": self.value,
                "tipo": self.tipo,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}
