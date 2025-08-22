# keep_alive.py
import os
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.get("/")
def home():
    return "OK", 200

def run():
    port = int(os.getenv("PORT", "8080"))  # สำคัญ: Render จะกำหนด $PORT มาให้
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
