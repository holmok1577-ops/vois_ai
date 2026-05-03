FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HTTP_PROXY= \
    HTTPS_PROXY= \
    ALL_PROXY=

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements-web.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "web_interface.server:app", "--host", "0.0.0.0", "--port", "8000"]
