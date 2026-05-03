# Vois AI

Голосовой AI-ассистент с веб-интерфейсом, постоянным микрофоном, потоковым распознаванием речи через Yandex SpeechKit, генерацией ответа через Yandex Foundation Models и озвучкой через SpeechKit TTS.

## Возможности

- Веб-интерфейс на FastAPI + WebSocket.
- Потоковое распознавание речи Yandex SpeechKit gRPC v3.
- Голосовой режим: включили микрофон один раз и продолжаете диалог.
- Автоматическое завершение реплики по паузе.
- Ответ текстом и голосом.
- Очередь воспроизведения, чтобы ответы ассистента не накладывались друг на друга.
- Контекст диалога хранится в памяти текущей сессии.
- Docker Compose для локального запуска и деплоя на VPS.

## Структура

```text
.
├── web_interface/
│   ├── index.html
│   └── server.py
├── telegram_bot/
├── google/
├── yandex/
├── voice_agent_core.py
├── Dockerfile
├── docker-compose.yml
├── requirements-web.txt
├── requirements.txt
├── env.example
└── STREAMING_STT_SETUP.md
```

Папки `google/` и `yandex/` содержат сгенерированные gRPC protobuf-клиенты Yandex Cloud API, нужные для SpeechKit v3.

## Переменные окружения

Создайте `.env` рядом с `docker-compose.yml`:

```env
YANDEX_CLOUD_API_KEY=your_api_key_here
YANDEX_CLOUD_FOLDER_ID=your_folder_id_here

SPEECHKIT_STT_MODE=streaming
SPEECHKIT_STT_ENDPOINT=https://stt.api.cloud.yandex.net/speech/v1/stt:recognize
SPEECHKIT_STT_GRPC_ENDPOINT=stt.api.cloud.yandex.net:443
SPEECHKIT_TTS_ENDPOINT=https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize
LLM_API_ENDPOINT=https://llm.api.cloud.yandex.net/llm/v1/completion

VECTOR_STORE_ID=
TELEGRAM_BOT_TOKEN=
```

Не коммитьте `.env`. Файл уже добавлен в `.gitignore`.

## Локальный запуск через Docker

```bash
docker compose build
docker compose up -d
docker compose logs -f voice-assistant
```

Открыть:

```text
http://127.0.0.1:8000/
```

Остановить:

```bash
docker compose down
```

## Деплой на VPS

Рекомендуемая ОС: Ubuntu 22.04 или Ubuntu 24.04.

### 1. Подключиться к серверу

```bash
ssh root@YOUR_SERVER_IP
```

Если используется другой пользователь:

```bash
ssh username@YOUR_SERVER_IP
```

### 2. Обновить систему

```bash
apt update
apt upgrade -y
```

### 3. Установить Docker

```bash
apt install -y ca-certificates curl gnupg git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Проверка:

```bash
docker --version
docker compose version
```

### 4. Клонировать репозиторий

```bash
mkdir -p /opt/vois-ai
cd /opt/vois-ai
git clone https://github.com/holmok1577-ops/vois_ai.git .
```

Если репозиторий приватный, используйте GitHub token или SSH-ключ.

### 5. Создать `.env`

```bash
nano .env
```

Вставьте значения из раздела "Переменные окружения".

### 6. Запустить ассистента

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f voice-assistant
```

Проверка на сервере:

```bash
curl -I http://127.0.0.1:8000/
```

Снаружи:

```text
http://YOUR_SERVER_IP:8000/
```

### 7. Открыть порт

Если включен `ufw`:

```bash
ufw allow OpenSSH
ufw allow 8000/tcp
ufw enable
ufw status
```

## Деплой с доменом и HTTPS

Для продакшена лучше не открывать порт `8000` наружу напрямую, а поставить Nginx и HTTPS.

### Nginx

```bash
apt install -y nginx
```

Пример конфига:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600;
    }
}
```

Сохранить в:

```bash
nano /etc/nginx/sites-available/vois-ai
ln -s /etc/nginx/sites-available/vois-ai /etc/nginx/sites-enabled/vois-ai
nginx -t
systemctl reload nginx
```

### HTTPS

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com
```

## Обновление на сервере

```bash
cd /opt/vois-ai
git pull
docker compose build
docker compose up -d
docker compose logs -f voice-assistant
```

## Полезные команды

```bash
docker compose ps
docker compose logs -f voice-assistant
docker compose restart voice-assistant
docker compose down
docker compose up -d --build
```

## Безопасность

- Не публикуйте `.env`.
- После тестов перевыпустите засвеченные API-ключи.
- Если ассистент доступен публично, любой посетитель может расходовать ваш Yandex Cloud API-ключ.
- Для публичного домена желательно добавить авторизацию или ограничение доступа.

## Проверка SpeechKit

Если голос не работает:

1. Проверьте, что `SPEECHKIT_STT_MODE=streaming`.
2. Проверьте, что `SPEECHKIT_STT_GRPC_ENDPOINT=stt.api.cloud.yandex.net:443`.
3. Проверьте права сервисного аккаунта: нужна роль `ai.speechkit-stt.user` или выше.
4. Посмотрите логи:

```bash
docker compose logs -f voice-assistant
```

## Примечания

Контейнер отключает `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, потому что gRPC SpeechKit может некорректно пытаться идти через системный proxy.
