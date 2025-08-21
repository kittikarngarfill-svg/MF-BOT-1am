# keep_alive.py
import os
from threading import Thread
from flask import Flask

app = Flask(__name__)

@app.get("/")
def home():
    return "MF_BOT is alive", 200

def _run():
    # Render ส่งพอร์ตผ่าน ENV ชื่อ PORT; ตั้งค่า default เผื่อรันท้องถิ่น
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=_run, daemon=True)
    t.start()