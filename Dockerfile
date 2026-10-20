FROM python:3.12-slim

WORKDIR /app

COPY storage/requirements.txt storage/requirements.txt
RUN pip install --no-cache-dir -r storage/requirements.txt

COPY . .

CMD ["python", "bot.py"]