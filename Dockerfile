# ใช้ Python 3.12 (เสถียรกับ nextcord voice)
FROM python:3.12-slim

# ติดตั้ง ffmpeg + libopus สำหรับเสียง
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libopus0 \
 && rm -rf /var/lib/apt/lists/*

# ติดตั้งไลบรารี Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอกโค้ดที่เหลือ
COPY . .

# ให้ log ไม่บัฟเฟอร์
ENV PYTHONUNBUFFERED=1

# รันบอท (คุณมี keep_alive แล้ว)
CMD ["python", "MF_BOT_1am.py"]