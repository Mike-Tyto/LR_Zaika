import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

log = logging.getLogger("secure_bank")

LINE_LIMIT = 2048
READ_TIMEOUT = 60
SESSION_MAX_COMMANDS = 200
SESSION_MAX_SECONDS = 300
CONNECTION_LIMIT = 32
AUTH_ATTEMPT_LIMIT = 5
AUTH_WINDOW = 60
HASH_SLOTS = 2
BALANCE_CAP = 100_000_000_000

LOGIN_PATTERN = re.compile(r"[a-zA-Z0-9_]{1,32}\Z")
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_-]{16,64}\Z")
AMOUNT_PATTERN = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,2})?")


def derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32,
        maxmem=64 * 1024 * 1024,
    )


def parse_amount(value: str) -> int:
    if not AMOUNT_PATTERN.fullmatch(value):
        raise ValueError("bad amount")
    cents = int(Decimal(value) * 100)
    if not 0 < cents <= BALANCE_CAP:
        raise ValueError("bad amount")
    return cents


def format_money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


class Storage:
    def __init__(self, path: Path):
        self.path = str(path)
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextmanager
    def session(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def bootstrap(self, credentials: dict):
        with self.session() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    login TEXT UNIQUE NOT NULL,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','user')),
                    balance INTEGER NOT NULL CHECK(balance >= 0 AND balance <= 100000000000)
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    from_id INTEGER NOT NULL REFERENCES users(id),
                    to_id INTEGER NOT NULL REFERENCES users(id),
                    amount INTEGER NOT NULL CHECK(amount > 0),
                    tx_token TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    UNIQUE(from_id, tx_token),
                    CHECK(from_id != to_id)
                );
            """)
            if db.execute("SELECT count(*) FROM users").fetchone()[0] > 0:
                return
            if not credentials or set(credentials) != {"admin", "alice", "bob"}:
                raise ValueError("need admin/alice/bob credentials")
            seed = [("admin", 100000000), ("alice", 500000), ("bob", 10000)]
            for uid, (login, balance) in enumerate(seed, 1):
                pwd = credentials[login]
                if not isinstance(pwd, str) or not 16 <= len(pwd) <= 128 or any(c.isspace() for c in pwd):
                    raise ValueError("bad password")
                salt = secrets.token_bytes(16)
                db.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, login, salt, derive_key(pwd, salt),
                     "admin" if uid == 1 else "user", balance),
                )
        os.chmod(self.path, 0o600)


class BankService:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._attempts = {}
        self._attempts_lock = threading.Lock()
        self._hash_slots = threading.BoundedSemaphore(HASH_SLOTS)
        self._dummy_salt = secrets.token_bytes(16)
        self._dummy_hash = derive_key(secrets.token_urlsafe(32), self._dummy_salt)

    def _authenticate(self, login: str, password: str):
        if not LOGIN_PATTERN.fullmatch(login) or not 1 <= len(password) <= 128:
            return None
        if not self._hash_slots.acquire(blocking=False):
            return None
        try:
            with self.storage.session() as db:
                row = db.execute(
                    "SELECT * FROM users WHERE login = ?", (login,)
                ).fetchone()
            if row:
                with self._attempts_lock:
                    now = time.monotonic()
                    recent = [t for t in self._attempts.get(login, []) if now - t < AUTH_WINDOW]
                    if len(recent) >= AUTH_ATTEMPT_LIMIT:
                        return None
                    self._attempts[login] = recent + [now]
            salt = row["salt"] if row else self._dummy_salt
            expected = row["password_hash"] if row else self._dummy_hash
            ok = hmac.compare_digest(derive_key(password, salt), expected)
            return row["id"] if row and ok else None
        finally:
            self._hash_slots.release()

    def _transfer(self, uid: int, to_id: int, amount: str, tx_token: str, comment: str) -> str:
        if not TOKEN_PATTERN.fullmatch(tx_token) or len(comment) > 200:
            raise ValueError("bad token or comment")
        cents = parse_amount(amount)
        if to_id == uid:
            raise ValueError("self-transfer")
        with self.storage.session() as db:
            db.execute("BEGIN IMMEDIATE")
            prev = db.execute(
                "SELECT * FROM transactions WHERE from_id=? AND tx_token=?",
                (uid, tx_token),
            ).fetchone()
            if prev:
                same = (prev["to_id"], prev["amount"], prev["comment"]) == (to_id, cents, comment)
                if not same:
                    raise ValueError("token conflict")
                return f"OK|Already processed|tx={prev['id']}"
            dst = db.execute("SELECT balance FROM users WHERE id=?", (to_id,)).fetchone()
            if dst is None or dst["balance"] + cents > BALANCE_CAP:
                raise ValueError("bad recipient or cap")
            changed = db.execute(
                "UPDATE users SET balance=balance-? WHERE id=? AND balance>=?",
                (cents, uid, cents),
            ).rowcount
            if changed != 1:
                raise ValueError("insufficient funds")
            db.execute("UPDATE users SET balance=balance+? WHERE id=?", (cents, to_id))
            tx = db.execute(
                "INSERT INTO transactions(from_id,to_id,amount,tx_token,comment) VALUES (?,?,?,?,?)",
                (uid, to_id, cents, tx_token, comment),
            )
            tx_id = tx.lastrowid
        log.info("transfer uid=%d tx=%d", uid, tx_id)
        return f"OK|Transfer completed|tx={tx_id}"

    def dispatch(self, uid, line: str):
        if any(ord(c) < 32 or ord(c) == 127 for c in line):
            raise ValueError("control chars")
        parts = line.split()
        if not parts:
            raise ValueError("empty")
        cmd, args = parts[0].upper(), parts[1:]

        if cmd == "QUIT" and not args:
            return uid, "BYE"
        if cmd == "HELP" and not args:
            return uid, "OK|LOGIN login password; BALANCE; TRANSFER to amount token [comment]; HISTORY [uid]; ADMIN USERS; QUIT"
        if cmd == "LOGIN":
            new_uid = self._authenticate(*args) if len(args) == 2 else None
            log.info("login=%s", "ok" if new_uid else "deny")
            return new_uid, "OK|Logged in" if new_uid else "FAIL|Invalid credentials or rate limit"
        if uid is None:
            return None, "ERR|Login required"

        with self.storage.session() as db:
            user = db.execute("SELECT id, role, balance FROM users WHERE id=?", (uid,)).fetchone()
            if cmd == "BALANCE" and not args:
                return uid, "OK|" + format_money(user["balance"])
            if cmd == "HISTORY" and len(args) <= 1:
                target = int(args[0]) if args else uid
                if target != uid:
                    return uid, "ERR|Access denied"
                rows = db.execute(
                    "SELECT id,ts,from_id,to_id,amount,comment FROM transactions "
                    "WHERE from_id=? OR to_id=? ORDER BY id DESC LIMIT 100",
                    (uid, uid),
                ).fetchall()
                return uid, "OK|" + json.dumps([dict(r) for r in rows], ensure_ascii=True)
            if cmd == "ADMIN":
                if user["role"] != "admin" or args != ["USERS"]:
                    return uid, "ERR|Access denied or unsupported admin operation"
                rows = db.execute("SELECT id,login,role,balance FROM users").fetchall()
                return uid, "OK|" + json.dumps([dict(r) for r in rows])

        if cmd == "TRANSFER" and len(args) >= 3:
            return uid, self._transfer(uid, int(args[0]), args[1], args[2], " ".join(args[3:]))
        raise ValueError("bad command")


class LineReader:
    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.buffer = b""

    def read(self) -> str:
        deadline = time.monotonic() + READ_TIMEOUT
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("line deadline")
            self.conn.settimeout(remaining)
            chunk = self.conn.recv(min(1024, LINE_LIMIT + 1 - len(self.buffer)))
            if not chunk:
                raise EOFError
            self.buffer += chunk
            if len(self.buffer) > LINE_LIMIT and b"\n" not in self.buffer:
                raise ValueError("line too long")
        raw, self.buffer = self.buffer.split(b"\n", 1)
        if len(raw) > LINE_LIMIT:
            raise ValueError("line too long")
        return raw.decode("utf-8")


class ConnectionHandler:
    def __init__(self, conn: socket.socket, bank: BankService):
        self.conn = conn
        self.bank = bank
        self.reader = LineReader(conn)

    def run(self):
        uid = None
        try:
            self.conn.settimeout(READ_TIMEOUT)
            self.conn.sendall(b"BANK SERVER READY\n")
            started = time.monotonic()
            for _ in range(SESSION_MAX_COMMANDS):
                if time.monotonic() - started > SESSION_MAX_SECONDS:
                    break
                line = self.reader.read()
                try:
                    uid, reply = self.bank.dispatch(uid, line)
                except ValueError:
                    reply = "ERR|Invalid request"
                except sqlite3.Error:
                    log.error("db error")
                    reply = "ERR|Storage unavailable"
                log.info("uid=%s reply=%s", uid, reply.split("|", 1)[0])
                self.conn.settimeout(READ_TIMEOUT)
                self.conn.sendall((reply + "\n").encode())
                if reply == "BYE":
                    break
        except (OSError, EOFError, ValueError):
            log.info("connection closed or invalid frame")
        finally:
            self.conn.close()


def run_server():
    os.umask(0o077)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    db_path = Path(os.environ.get("BANK_DB", "data/bank.sqlite3"))
    storage = Storage(db_path)
    credentials = None
    if not db_path.exists():
        credentials = json.loads(
            Path(os.environ.get("BANK_CREDENTIALS_FILE", "secrets/users.json")).read_text()
        )
    storage.bootstrap(credentials)
    bank = BankService(storage)

    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(
        os.environ.get("BANK_CERT", "secrets/server.crt"),
        os.environ.get("BANK_KEY", "secrets/server.key"),
    )
    slots = threading.BoundedSemaphore(CONNECTION_LIMIT)

    def serve_one(raw: socket.socket):
        try:
            raw.settimeout(5)
            with tls.wrap_socket(raw, server_side=True) as conn:
                ConnectionHandler(conn, bank).run()
        except OSError:
            log.info("TLS handshake rejected")
        finally:
            raw.close()
            slots.release()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((os.environ.get("BANK_HOST", "0.0.0.0"), 9999))
        srv.listen(32)
        log.info("TLS bank ready port=9999")
        while True:
            conn, _ = srv.accept()
            if not slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=serve_one, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    run_server()