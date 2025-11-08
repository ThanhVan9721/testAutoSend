from flask import Flask, send_file
import requests
from datetime import datetime
import os
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips

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

def createVideo():
    # ====== Cấu hình đầu vào ======
    IMAGE_FOLDER = "images"        # thư mục chứa ảnh
    AUDIO_PATH = "output.mp3"      # file giọng đọc
    OUTPUT_PATH = "output_video.mp4"

    # ====== Nạp âm thanh ======
    audio = AudioFileClip(AUDIO_PATH)
    audio_duration = audio.duration  # thời lượng âm thanh (giây)

    # ====== Đọc danh sách ảnh từ thư mục ======
    image_files = sorted([
        os.path.join(IMAGE_FOLDER, f)
        for f in os.listdir(IMAGE_FOLDER)
        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
    ])

    if not image_files:
        raise ValueError("❌ Không tìm thấy ảnh trong thư mục 'images'!")

    # ====== Tính thời lượng mỗi ảnh ======
    duration_per_image = audio_duration / len(image_files)

    # ====== Tạo danh sách ImageClip ======
    clips = [
        ImageClip(img).set_duration(duration_per_image)
        for img in image_files
    ]

    # ====== Ghép các ảnh thành một video ======
    video = concatenate_videoclips(clips, method="compose")

    # ====== Gắn âm thanh vào video ======
    final = video.set_audio(audio)

    # ====== Xuất video ======
    final.write_videofile(
        OUTPUT_PATH,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=2,
        preset="ultrafast"   # nhanh, nhẹ
    )

@app.route("/")
def home():
    """Khi truy cập URL thì gửi dữ liệu luôn"""
    result = post_time()
    return result

@app.route("/taovideo")
def create():
    createVideo()
    return f"Đã tạo video"

@app.route("/view")
def view():
    return send_file("output_video.mp4", mimetype="video/mp4")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
