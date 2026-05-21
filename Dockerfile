# Django-приложение socworker + зависимости из requirements.txt
# Базу MySQL запускайте через docker-compose (сервис db).

FROM python:3.10-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# В compose используется command с migrate; локально можно переопределить.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
