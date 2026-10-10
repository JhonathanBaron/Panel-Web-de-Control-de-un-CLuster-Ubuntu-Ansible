import threading
import time
import serial

from .config import Config


class Arduino:
    def __init__(self):
        self._lock = threading.Lock()
        self._arduino = None
        self._connect()

    def _connect(self):
        try:
            self._arduino = serial.Serial(
                Config.ARDUINO_PORT, Config.ARDUINO_BAUD, timeout=1)
            time.sleep(2)
            print(f"[Arduino] Conectado en {Config.ARDUINO_PORT}")
        except Exception as e:
            print(f"[Arduino] Sin conexión: {e}")
            self._arduino = None

    @property
    def connected(self):
        return self._arduino is not None and self._arduino.is_open

    def send(self, pin, value):
        with self._lock:
            if not self.connected:
                return False
            try:
                v = int(value)
                if str(pin) in ("11", "10", "6", "5"):
                    v = 255 - v
                cmd = f"{pin}:{v}\n"
                self._arduino.write(cmd.encode('utf-8'))
                return True
            except Exception as e:
                print(f"[Arduino] Error enviando: {e}")
                self._arduino = None
                return False

    def reconnect_loop(self):
        while True:
            if not self.connected:
                self._connect()
            time.sleep(Config.ARDUINO_RETRY_DELAY)


arduino = Arduino()
