import requests
from datetime import datetime
import time

# 🔸 Thay link webhook Google Apps Script của bạn
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbz-J9G9rqR4LFw3JZR8yZjHIhtUcyIR_Gh1xVUCKOOsf3MzmXIx1sM2DfNdE9rP81a3/exec"

def post_time():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {"time": current_time}

    try:
        response = requests.post(WEBHOOK_URL, json=data)
        if response.status_code == 200:
            print("✅ Đã gửi:", current_time)
        else:
            print("❌ Lỗi:", response.status_code, response.text)
    except Exception as e:
        print("⚠️ Lỗi kết nối:", e)

# 🔁 Gửi mỗi 5 phút
if __name__ == "__main__":
    while True:
        post_time()
        time.sleep(5 * 60)  # 5 phút = 300 giây
