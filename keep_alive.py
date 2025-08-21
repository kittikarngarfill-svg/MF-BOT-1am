# keep_alive.py
import os
from threading import Thread
from flask import Flask

app = Flask(__name__)

@app.get("/")
def home():
    return "MF_BOT is alive", 200

def _run():
    # Render ใส่ PORT มาให้ใน ENV; ใช้ค่านี้เสมอ
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=_run, daemon=True)
    t.start()