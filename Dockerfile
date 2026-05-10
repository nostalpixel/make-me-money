FROM python:3.11-slim

WORKDIR /app

COPY deps/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY social/ ./social/

WORKDIR /app/bot
CMD ["python", "main.py"]
