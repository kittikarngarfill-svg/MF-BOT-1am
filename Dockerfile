FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ติดตั้ง dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --root-user-action=ignore

# คัดลอกซอร์สทั้งหมด
COPY . .

# เริ่มโปรเซสเดียว ที่มีทั้งเว็บ keep-alive และ Discord bot
# (keep_alive() จะถูกเรียกใน MF_BOT_1am.py)
CMD ["python", "MF_BOT_1am.py"]
