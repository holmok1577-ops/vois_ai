# Потоковое распознавание SpeechKit v3

Проект поддерживает два режима STT:

- `batch` - старый HTTP v1 режим, когда фраза сначала накапливается локально, затем отправляется в SpeechKit.
- `streaming` - gRPC v3 режим, когда PCM16-чанки с микрофона сразу отправляются в SpeechKit, а интерфейс получает промежуточные и финальные результаты.

## 1. Установить зависимости

```powershell
.\new-env\Scripts\python.exe -m pip install -r requirements.txt
```

Если используете другое окружение, замените путь к `python.exe`.

## 2. Сгенерировать gRPC-клиент Yandex Cloud API

Склонируйте официальный репозиторий Yandex Cloud API рядом с проектом или в любое удобное место:

```powershell
git clone https://github.com/yandex-cloud/cloudapi
```

Из корня проекта выполните генерацию служебных Google proto:

```powershell
.\new-env\Scripts\python.exe -m grpc_tools.protoc `
  -I C:\path\to\cloudapi\third_party\googleapis `
  --python_out=. `
  --grpc_python_out=. `
  C:\path\to\cloudapi\third_party\googleapis\google\api\http.proto `
  C:\path\to\cloudapi\third_party\googleapis\google\api\annotations.proto `
  C:\path\to\cloudapi\third_party\googleapis\google\rpc\status.proto
```

Затем сгенерируйте Yandex Cloud proto:

```powershell
.\new-env\Scripts\python.exe -m grpc_tools.protoc `
  -I C:\path\to\cloudapi `
  -I C:\path\to\cloudapi\third_party\googleapis `
  --python_out=. `
  --grpc_python_out=. `
  C:\path\to\cloudapi\yandex\cloud\api\operation.proto `
  C:\path\to\cloudapi\yandex\cloud\operation\operation.proto `
  C:\path\to\cloudapi\yandex\cloud\validation.proto `
  C:\path\to\cloudapi\yandex\cloud\ai\stt\v3\package_options.proto `
  C:\path\to\cloudapi\yandex\cloud\ai\stt\v3\stt_service.proto `
  C:\path\to\cloudapi\yandex\cloud\ai\stt\v3\stt.proto
```

После этого в проекте появятся пакеты `google/...` и `yandex/...` со сгенерированными файлами.

## 3. Включить streaming-режим

В `.env`:

```env
SPEECHKIT_STT_MODE=streaming
SPEECHKIT_STT_GRPC_ENDPOINT=stt.api.cloud.yandex.net:443
```

API-ключ должен принадлежать сервисному аккаунту с ролью `ai.speechkit-stt.user` или выше.

## 4. Запуск

Веб-интерфейс:

```powershell
.\new-env\Scripts\python.exe -m uvicorn web_interface.server:app --host 0.0.0.0 --port 8000
```

Консольный агент:

```powershell
.\new-env\Scripts\python.exe .\voice-agent.py
```
