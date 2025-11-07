from flask import Flask
import requests
from datetime import datetime

app = Flask(__name__)

# 🔸 Link webhook Apps Script thật của bạn
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbz-J9G9rqR4LFw3JZR8yZjHIhtUcyIR_Gh1xVUCKOOsf3MzmXIx1sM2DfNdE9rP81a3/exec"

def post_time():
    """Gửi thời gian hiện tại lên Google Sheet"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {"time": current_time}

    try:
        r = requests.post(WEBHOOK_URL, json=data)
        if r.status_code == 200:
            return f"✅ Đã gửi {current_time} lên Google Sheet."
        else:
            return f"❌ Lỗi ({r.status_code}): {r.text}"
    except Exception as e:
        return f"⚠️ Lỗi kết nối: {e}"

@app.route("/")
def home():
    """Khi truy cập URL thì gửi dữ liệu luôn"""
    result = post_time()
    return result

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
