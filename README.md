# messenger-server

`messenger-server` — серверная часть мессенджера на `FastAPI` с поддержкой REST API, JWT-аутентификации и доставки событий в реальном времени через WebSocket.

Проект построен вокруг модели клиента «сначала офлайн»:
- интерфейс клиента читает данные из локальной SQLite на устройстве;
- REST используется как каноничный путь записи и восстановления состояния;
- WebSocket добавляет низкую задержку для уже зафиксированных на сервере событий.

## Возможности

- Регистрация, вход, обновление и отзыв токенов.
- Поиск пользователей и получение профиля текущего пользователя.
- Создание/получение личных диалогов.
- Отправка и чтение сообщений с упорядочиванием по `seq` внутри диалога.
- Идемпотентность отправки сообщений по паре `(sender_id, client_message_id)`.
- Эндпоинты синхронизации для начальной загрузки и догонки пропущенных изменений.
- WebSocket `/v1/ws` с подписками на диалоги и доставкой событий `message.created` и `conversation.updated`.
- Транзакционный журнал исходящих событий для надёжной публикации realtime-событий.

## Технологии

- Python 3.13+
- FastAPI
- SQLAlchemy
- SQLite (с архитектурной готовностью к переходу на PostgreSQL)
- JWT (`python-jose`)
- Argon2 (`passlib[argon2]`)
- Pytest

## Структура проекта

- `app/main.py` — инициализация приложения, CORS, жизненный цикл, запуск realtime-диспетчера.
- `app/api/v1/` — REST-роуты и WebSocket-роут.
- `app/services/` — бизнес-логика (аутентификация, диалоги, сообщения, realtime).
- `app/realtime/` — протокол, менеджер соединений, публикация и диспетчеризация событий.
- `app/models/` — SQLAlchemy-модели.
- `app/schemas/` — Pydantic-схемы.
- `app/core/` — настройки, безопасность, ошибки, логирование, ограничение частоты запросов.
- `tests/` — тесты аутентификации, сообщений, диалогов, WebSocket и диспетчера исходящих событий.

## API

Базовый префикс: `/v1`

### Аутентификация

- `POST /v1/auth/register`
- `POST /v1/auth/login`
- `POST /v1/auth/refresh`
- `POST /v1/auth/logout`

### Пользователи

- `GET /v1/users/me`
- `GET /v1/users/search?query=&limit=`
- `POST /v1/users/batch`

### Диалоги

- `GET /v1/conversations`
- `POST /v1/conversations/direct`

### Сообщения

- `GET /v1/conversations/{conversation_id}/messages?after_seq=&limit=`
- `POST /v1/conversations/{conversation_id}/messages`

### Синхронизация

- `GET /v1/sync/bootstrap`
- `GET /v1/sync/changes?after_seq_by_conversation=...`

`/v1/sync/bootstrap` возвращает `me`, `user`, `users`, `conversations`, `recent_messages`, `recentMessages`.

`/v1/sync/changes` возвращает плоский дельта-пакет: `users`, `conversations`, `messages`.

## WebSocket

Эндпоинт: `WS /v1/ws`

Аутентификация:
- предпочтительно заголовок `Authorization: Bearer <access_token>`;
- запасной вариант: `?access_token=<jwt>`.

Поддерживаемые команды клиента:
- `subscribe`
- `unsubscribe`
- `ping`

Ключевые исходящие фреймы сервера:
- `connection.welcome`
- `ack`
- `pong`
- `error`
- `message.created`
- `conversation.updated`

Семантика доставки:
- порядок гарантируется внутри диалога через `seq`;
- доставка по WebSocket выполняется по принципу «как получится»;
- полнота и корректность восстанавливаются через `/v1/sync/changes`.

## Формат ответов

Единый HTTP-конверт:
- успех: `{ "data": ... }`
- ошибка: `{ "error": { "code": "...", "message": "...", "details"?: ... } }`

## Быстрый старт

### 1. Установка зависимостей

```bash
uv sync
```

Если `uv` не используется, можно установить зависимости любым эквивалентным способом из `pyproject.toml`.

### 2. Запуск сервера

```bash
uv run python main.py
```

Сервер по умолчанию стартует на `0.0.0.0:8000`.

Проверка доступности:

```bash
curl http://localhost:8000/health
```

## Переменные окружения

Основные настройки (см. `app/core/settings.py`):

- `DEBUG` (по умолчанию `false`)
- `APP_NAME` (по умолчанию `Messenger Server`)
- `API_V1_PREFIX` (по умолчанию `/v1`)
- `DATABASE_URL` (по умолчанию `sqlite:///./app.db`)
- `SECRET_KEY`
- `JWT_ALGORITHM` (по умолчанию `HS256`)
- `ACCESS_TOKEN_EXPIRE_MINUTES` (по умолчанию `15`)
- `REFRESH_TOKEN_EXPIRE_DAYS` (по умолчанию `30`)
- `CORS_ORIGINS` (строка через запятую)
- `MESSAGE_MAX_LENGTH`
- `AUTH_RATE_LIMIT_WINDOW_SECONDS`
- `AUTH_RATE_LIMIT_MAX_REQUESTS`
- `WS_HEARTBEAT_SEC`
- `WS_IDLE_TIMEOUT_SEC`
- `WS_MAX_COMMAND_BYTES`
- `WS_MAX_IDS_PER_SUBSCRIBE`
- `WS_MAX_SUBSCRIPTIONS_PER_CONNECTION`
- `WS_RATE_LIMIT_WINDOW_SEC`
- `WS_RATE_LIMIT_MAX_COMMANDS`
- `REALTIME_DISPATCHER_ENABLED`
- `REALTIME_DISPATCHER_POLL_MS`
- `REALTIME_DISPATCHER_BATCH_SIZE`

## Тесты

Запуск всех тестов:

```bash
uv run pytest
```

Покрываются:
- аутентификация и ротация refresh-токенов;
- идемпотентность отправки и последовательность сообщений;
- доставка событий в реальном времени через WebSocket;
- повторы и публикация событий из транзакционного журнала.

## Архитектурные документы

- `backend_architecture.md`
- `architecture_websockets.md`
- `client_websocket_architecture.md`
- `additional_info.md`

Эти файлы описывают целевую серверную архитектуру и клиентскую интеграцию для офлайн-ориентированного сценария.
