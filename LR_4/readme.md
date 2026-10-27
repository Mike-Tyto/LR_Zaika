# Анализ кода через semgrep

## Подготовка

* Вам потребуется ОС Linux / MacOS
* Установить semgrep с помощью команды `snap install semgrep` или `brew install semgrep`
* Скачать правила semgrep с официального репозитория [semgrep-rules](https://github.com/semgrep/semgrep-rules/tree/develop/python)

## Задание

Провести анализ кода через semgrep

Запуск осуществляется через команду следующий скрипт:
 
```
#!/bin/bash
set -e

mkdir -p semgrep-rules-yaml

find semgrep-rules -type f \( -name "*.yaml" -o -name "*.yml" \) \
    -exec cp --parents {} semgrep-rules-yaml/ \;

semgrep --config semgrep-rules-yaml/ \
        --json \
        --output=semgrep-report.json \
        main.py
```

В конце ожидается составленная таблица по результатам semgrep с приведенными выводами

[!] Можно воспользоваться ИИ

<img width="1395" height="648" alt="image" src="https://github.com/user-attachments/assets/df3c7660-3e0d-4d89-a72c-da5720a1f702" />

## О коде

| Компонент | Что это | Назначение |
|---|---|---|
| `main.py` | TCP-сервер банка | Принимает подключения, обрабатывает команды `LOGIN`, `BALANCE`, `TRANSFER`, `HISTORY`, `ADMIN`, `QUIT`, хранит данные в `bank_db.json` |
| `bank_client.py` | Клиентская обёртка | Подключается к серверу, отправляет команды и читает ответы; используется всеми атаками |
| `attack_idor.py` | Атака IDOR | Перебирает `HISTORY <uid>` и читает историю транзакций чужих пользователей |
| `attack_negative_transfer.py` | Атака отрицательным переводом | Отправляет `TRANSFER` с отрицательной суммой, чтобы увеличить свой баланс |
| `attack_race.py` | Race condition (TOCTOU) | Многопоточно выполняет переводы, эксплуатируя задержку между проверкой баланса и списанием |
| `attack_replay.py` | Replay-атака | Повторно отправляет ранее перехваченную команду `TRANSFER` |
| `attack_self_transfer.py` | Self-transfer | Переводит отрицательную сумму самому себе для накрутки баланса |
| `attack_slowloris.py` | Slowloris | Открывает много соединений и шлёт по 1 байту, удерживая ресурсы сервера |
| `attack_sqli.py` | SQL-инъекция в логине | Пробует payload'ы вида `' OR '1'='1` для обхода аутентификации |
| `attack_admin_sql.py` | SQL-инъекция в `ADMIN` | Через `LOGIN ' OR '1'='1 x` получает роль admin и выполняет произвольные SQL-запросы |
| `attack_tamper_db.py` | Подмена БД | Меняет `bank_db.json` напрямую, например выставляет `admin.balance = 999999999` |
| `attack_bruteforce.py` | Брутфорс | Перебирает пароль `alice` по словарю |
| `attack_dos.py` | DoS | Открывает очень много TCP-соединений и удерживает их |
| `attack_fuzz.py` | Фаззинг | Шлёт некорректные/граничные команды для поиска ошибок и падений |
