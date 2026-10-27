import socket
import ssl
import sys


class BankClient:
    def __init__(self, host="127.0.0.1", port=9999, cafile="secrets/server.crt"):
        context = ssl.create_default_context(cafile=cafile)
        raw = socket.create_connection((host, port), timeout=5)
        self.sock = context.wrap_socket(raw, server_hostname="localhost")
        self.buffer = b""
        self._readline()

    def _readline(self):
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Server closed connection")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return line.decode(errors="ignore").strip()

    def cmd(self, line):
        self.sock.sendall(line.encode() + b"\n")
        return self._readline()

    def close(self):
        try:
            self.cmd("QUIT")
        except Exception:
            pass
        self.sock.close()


if __name__ == "__main__":
    c = BankClient()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            print(c.cmd(line))
    finally:
        c.close()