import http.client
import json
import logging
from datetime import datetime

HOST = "127.0.0.1"
PORT = 8080

LOG_FILE = "client.log"


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("game_client")
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


def request(method: str, path: str, body=None):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=5)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    body_bytes = json.dumps(body).encode("utf-8") if body is not None else None

    log.info(">>> %s %s", method, path)
    if body is not None:
        log.debug("    body: %s", body)

    try:
        conn.request(method, path, body=body_bytes, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")

        log.info("<<< %s %s", resp.status, resp.reason)
        log.info("    %s", data)
        log.info("-" * 60)
    except Exception as e:
        log.error("!!! Ошибка при %s %s: %s", method, path, e)
        log.info("-" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("Запуск клиента: %s", datetime.now().isoformat(timespec="seconds"))
    log.info("=" * 60)

    # 1. Список пользователей
    request("GET", "/users")

    # 2. Конкретный пользователь
    request("GET", "/users/user2")

    # 3. Начисление очков
    request("POST", "/users/user1/score", {"score": 500})

    # 4. Несуществующий пользователь
    request("GET", "/users/user99")

    # 5. Начисление очков с пустым телом запроса
    request("POST", "/users/user1/score")

    # 6. Начисление очков с неверным типом score
    request("POST", "/users/user1/score", {"score": "abc"})

    # 7. Несуществующий маршрут
    request("GET", "/foo")

    # 8. Удаление всех пользователей
    request("DELETE", "/users")

    log.info("Клиент завершил работу")