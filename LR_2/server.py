import json
import logging
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from pydantic import BaseModel, Field, ValidationError, ConfigDict

HOST = "127.0.0.1"
PORT = 8080

LOG_FILE = "server.log"


class UserStats(BaseModel):
    name: str = Field(..., description="Имя игрока")
    game: str = Field(..., description="Название игры")
    level: int = Field(..., ge=0, description="Уровень игрока")
    score: int = Field(..., ge=0, description="Количество очков")
    playtime_hours: int = Field(..., ge=0, description="Время в игре (часы)")


class ScoreUpdate(BaseModel):
    model_config = ConfigDict(strict=True)
    score: int = Field(..., description="Сколько очков добавить")


USERS_DATA: dict[str, UserStats] = {
    "user1": UserStats(name="Алексей", game="Dota 2", level=42, score=15320, playtime_hours=210),
    "user2": UserStats(name="Мария", game="Valorant", level=30, score=9870, playtime_hours=95),
    "user3": UserStats(name="Игорь", game="CS2", level=55, score=21000, playtime_hours=340),
}


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("game_server")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


log = setup_logger()


class GameStatsHandler(BaseHTTPRequestHandler):

    def send_json(self, code: int, payload):
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionResetError, BrokenPipeError):
            log.warning("Клиент разорвал соединение при отправке ответа на %s %s",
                        self.command, self.path)

    def log_message(self, fmt, *args):
        code = args[1] if len(args) > 1 else "?"
        log.info("[%s] %s -> %s", self.command, self.path, code)

    def log_error(self, fmt, *args):
        log.error("HTTP-ошибка: %s", fmt % args)

    def log_request(self, code="-", size="-"):
        self.log_message('"%s" %s %s', self.requestline, code, size)

    def do_GET(self):
        try:
            parts = [p for p in self.path.split("/") if p]

            if parts == ["users"]:
                self.send_json(200, {uid: u.model_dump() for uid, u in USERS_DATA.items()})
                return

            if len(parts) == 2 and parts[0] == "users":
                user = USERS_DATA.get(parts[1])
                if user is None:
                    self.send_json(404, {"error": "Пользователь не найден"})
                else:
                    self.send_json(200, user.model_dump())
                return

            self.send_json(404, {"error": "Маршрут не найден"})

        except Exception as e:
            log.exception("Необработанная ошибка в do_GET")
            self.send_json(500, {"error": f"Внутренняя ошибка сервера: {e}"})

    def do_POST(self):
        try:
            parts = [p for p in self.path.split("/") if p]

            if not (len(parts) == 3 and parts[0] == "users" and parts[2] == "score"):
                self.send_json(404, {"error": "Маршрут не найден"})
                return

            user = USERS_DATA.get(parts[1])
            if user is None:
                self.send_json(404, {"error": "Пользователь не найден"})
                return

            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self.send_json(400, {"error": "Некорректный Content-Length"})
                return

            raw = self.rfile.read(length) if length > 0 else b""
            if not raw:
                self.send_json(400, {"error": "Тело запроса пустое"})
                return

            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(400, {"error": "Невалидный JSON"})
                return

            try:
                update = ScoreUpdate.model_validate(data)
            except ValidationError as e:
                first = e.errors()[0]
                self.send_json(400, {"error": first["msg"]})
                return

            user.score += update.score
            self.send_json(200, user.model_dump())

        except (ConnectionResetError, BrokenPipeError):
            log.warning("Клиент разорвал соединение во время POST %s", self.path)
        except Exception as e:
            log.exception("Необработанная ошибка в do_POST")
            try:
                self.send_json(500, {"error": f"Внутренняя ошибка сервера: {e}"})
            except (ConnectionResetError, BrokenPipeError):
                log.warning("Не удалось отправить 500 — соединение уже закрыто")

    def do_DELETE(self):
        self.send_json(405, {"error": "Метод не поддерживается"})

    def do_PUT(self):
        self.send_json(405, {"error": "Метод не поддерживается"})

    def do_PATCH(self):
        self.send_json(405, {"error": "Метод не поддерживается"})


def run():
    server = HTTPServer((HOST, PORT), GameStatsHandler)

    log.info("=" * 60)
    log.info("Запуск сервера: %s", datetime.now().isoformat(timespec="seconds"))
    log.info("Адрес: http://%s:%s", HOST, PORT)
    log.info("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Получен Ctrl+C, остановка сервера...")
    finally:
        server.server_close()
        log.info("Сервер остановлен")
        logging.shutdown()


if __name__ == "__main__":
    run()