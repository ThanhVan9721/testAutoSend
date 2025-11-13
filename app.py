from flask import Flask, send_file
import requests
from datetime import datetime
import os
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips
from openai import OpenAI
import feedparser
from bs4 import BeautifulSoup
import re
import asyncio
import edge_tts
import hashlib
import shutil
import subprocess
import io
import glob
import json
app = Flask(__name__)

async def createVideo():
    print("Start Tạo video")
    IMAGE_FOLDER = "images"
    AUDIO_PATH = "output.mp3"
    OUTPUT_PATH = "output_video.mp4"

    # ===== Lấy danh sách ảnh =====
    images = sorted(glob.glob(os.path.join(IMAGE_FOLDER, "*")), key=os.path.getctime)
    if not images:
        raise ValueError("⚠️ Không tìm thấy hình ảnh nào trong thư mục images!")

    # ===== Lấy độ dài âm thanh =====
    cmd_probe = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", AUDIO_PATH
    ]
    result = subprocess.run(cmd_probe, capture_output=True, text=True, check=True)
    duration = float(json.loads(result.stdout)["format"]["duration"])

    # ===== Tính thời lượng mỗi ảnh =====
    DURATION_PER_IMAGE = duration / len(images)
    print(f"🎵 Âm thanh dài {duration:.2f}s → mỗi ảnh {DURATION_PER_IMAGE:.2f}s")

    # ===== Tạo list.txt =====
    list_file = "list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for img in images:
            f.write(f"file '{img}'\n")
            f.write(f"duration {DURATION_PER_IMAGE}\n")
        f.write(f"file '{images[-1]}'\n")

    # ===== Tạo video từ ảnh =====
    temp_video = "temp_video.mp4"
    cmd_video = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-r", "30",
        "-pix_fmt", "yuv420p",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264",
        temp_video
    ]
    subprocess.run(cmd_video, check=True)

    # ===== Ghép video + âm thanh =====
    cmd_merge = [
        "ffmpeg", "-y",
        "-i", temp_video,
        "-i", AUDIO_PATH,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        OUTPUT_PATH
    ]
    subprocess.run(cmd_merge, check=True)

    os.remove(temp_video)
    os.remove(list_file)
    print("End Tạo video")

async def getNewPost24h():
    print("Start lấy bài viết mới")
    # ====== Cấu hình ======
    rss_url = "https://cdn.24h.com.vn/upload/rss/anninhhinhsu.rss"
    google_script_url = 'https://script.google.com/macros/s/AKfycbzpFYZwnJXnOSkoimpjUJzSuz3xH88Tfn9t9-BNjvfb4H1SXQ8XzfLjgr0dWFHoe8Zt/exec'
    save_folder = "images"

    # ====== Xóa thư mục ảnh cũ nếu có ======
    if os.path.exists(save_folder):
        shutil.rmtree(save_folder)
        print(f"🧹 Đã xóa thư mục cũ: {save_folder}")
        
    os.makedirs(save_folder)

    # ====== Hàm tải ảnh ======
    def download_image(url, prefix="img", width=1080, height=1920):
        try:
            if not url or not url.startswith("http"):
                return None

            # Lấy phần mở rộng file
            ext = os.path.splitext(url.split("?")[0])[-1].lower()
            if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
                ext = ".jpg"

            # Tạo tên file duy nhất
            filename = f"{prefix}_{hashlib.md5(url.encode()).hexdigest()[:10]}{ext}"
            filepath = os.path.join(save_folder, filename)

            # Nếu ảnh đã tồn tại thì bỏ qua
            if os.path.exists(filepath):
                return filepath

            # Tải ảnh vào bộ nhớ (Bytes)
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                print(f"⚠️ Lỗi tải ảnh: {url}")
                return None

            # Dùng FFmpeg để resize, căn giữa + thêm nền đen
            # force_original_aspect_ratio=decrease -> giữ nguyên tỉ lệ ảnh
            # pad -> thêm viền đen cho đủ khung TikTok 1080x1920
            img_bytes = io.BytesIO(response.content)
            cmd = [
                "ffmpeg", "-y",                  # Ghi đè file nếu có
                "-i", "pipe:0",                  # Nhận ảnh từ stdin (bộ nhớ)
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
                filepath
            ]

            subprocess.run(
                cmd,
                input=img_bytes.read(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            if os.path.exists(filepath):
                print(f"✅ Đã tải và resize (FFmpeg): {filename}")
                return filepath
            else:
                print(f"⚠️ FFmpeg không tạo được file: {filename}")
                return None

        except Exception as e:
            print(f"❌ Lỗi khi xử lý ảnh {url}: {e}")
            return None


    # ====== Lấy dữ liệu đã có trên Google Sheet ======
    r = requests.get(google_script_url)
    dataInFiles = r.json()
    titles_in_sheet = [x["title"] for x in dataInFiles]


    # ====== Đọc RSS và xử lý từng bài ======
    feed = feedparser.parse(rss_url)
    contentNewPost = ""
    for entry in feed.entries:
        title = entry.title
        link = entry.link

        # Nếu bài viết đã tồn tại thì bỏ qua ngay
        if title in titles_in_sheet:
            continue

        # ===== Lấy ảnh chính từ RSS =====
        image_url = None
        if 'media_content' in entry and len(entry.media_content) > 0:
            image_url = entry.media_content[0]['url']
        else:
            match = re.search(r'<img[^>]+src="([^">]+)"', entry.summary)
            if match:
                image_url = match.group(1)

        # ===== Lấy nội dung chi tiết =====
        try:
            response = requests.get(link, timeout=10)
            response.encoding = "utf-8"
            soup = BeautifulSoup(response.text, "html.parser")
            article_tag = soup.find("article")

            if article_tag:
                for tag in article_tag(["script", "style", "iframe", "figure", "div"]):
                    tag.decompose()
                content_text = article_tag.get_text(separator="\n", strip=True)
            else:
                content_text = "Không tìm thấy thẻ <article>."
        except Exception as e:
            content_text = f"Lỗi khi tải nội dung: {e}"

        # ===== Gửi dữ liệu lên Google Sheet =====
        newData = {
            "title": title,
            "link": link,
            "image": image_url,
            "content": content_text
        }
        contentNewPost = content_text
        response = requests.post(google_script_url, json=newData)

        try:
            if image_url:
                download_image(image_url, prefix="main")

            if article_tag:
                for img_tag in article_tag.find_all("img"):
                    img_src = img_tag.get("src")
                    if img_src and img_src.startswith("http"):
                        download_image(img_src, prefix="content")
        except Exception as e:
            print(f"⚠️ Lỗi khi tải ảnh trong bài: {e}")

        break
    print("End lấy bài viết mới")
    return contentNewPost

        

async def editContent(content):
    print("Start edit nội dung bài viết")
    client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="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",
    )
    completion = client.chat.completions.create(
    extra_headers={
        "HTTP-Referer": "http://localhost:8080", # Optional. Site URL for rankings on openrouter.ai.
        "X-Title": "Test", # Optional. Site title for rankings on openrouter.ai.
    },
    extra_body={},
    model="openai/gpt-4o-mini",
    messages=[
        {
        "role": "system",
        "content": """
            Bạn là một biên tập viên thời sự chuyên nghiệp, chuyên đọc các bản tin ngắn trên TikTok và YouTube Shorts.

    Nhiệm vụ của bạn là chuyển thể nội dung bài báo mà người dùng cung cấp thành một bản tin ngắn, rõ ràng, mạch lạc, nghiêm túc và dễ nghe — giống như đang được đọc trong một video thời sự ngắn.

    -------------------------------------
    🎯 MỤC TIÊU:
    - Giữ nguyên nội dung chính xác và trung thực tuyệt đối theo bài báo gốc, không thêm, không bớt, không suy diễn.
    - Diễn đạt lại bằng ngôn ngữ nói tự nhiên, gãy gọn, rõ ý, dễ nghe cho người xem video ngắn.
    - Giữ nguyên số, Chuyển đổi toàn bộ ngày tháng, ký hiệu và đơn vị đo sang dạng đọc tự nhiên, ví dụ:
    • “24/11” → “24 tháng 11”
    • “km” → “ki-lô-mét”
    • “%” → “phần trăm”
    • “TP.HCM” → “thành phố Hồ Chí Minh”
    - Không có lời mở đầu như “Bản tin hôm nay…”, “Sau đây là nội dung…”  
    và không có lời kết như “Đó là những thông tin đáng chú ý…”.

    -------------------------------------
    📋 YÊU CẦU CỤ THỂ:
    1. Giữ nguyên mạch thông tin và ý nghĩa gốc, không thêm bình luận hoặc cảm xúc cá nhân.
    2. Câu văn ngắn, tự nhiên, rõ nghĩa, chia nhịp hợp lý để giọng đọc máy dễ nghe.
    3. Nếu bài viết có nhiều phần, có thể dùng cụm chuyển tiếp tự nhiên, trung lập như:
    • “Cơ quan chức năng cho biết…”  
    • “Tại hiện trường…”  
    • “Theo ghi nhận ban đầu…”  
    • “Cùng thời điểm đó…”  
    4. Không sử dụng ký tự đặc biệt như “/”, “%”, “#”, “:”, “( )” trừ khi bắt buộc.
    5. Giọng điệu trung lập, nghiêm túc, tin cậy, giống phong cách thời sự truyền hình.

    -------------------------------------
    🗣️ ĐẦU RA MONG MUỐN:
    - Một bản tin ngắn, rõ ràng, trung thực, không lời dẫn, không lời kết.
    - Diễn đạt bằng ngôn ngữ nói tự nhiên, phù hợp để chuyển thành giọng đọc tự động bằng thư viện edge_tts.
    - Dễ nghe, mạch lạc, nhịp độ vừa phải, giữ đúng phong cách thời sự chuyên nghiệp.
            """
    },
        {
            "role": "user",
            "content": f"""Đây là bài báo: 
                        {content}
                    """
        }
    ]
    )
    print("End edit nội dung bài viết")
    return completion.choices[0].message.content

async def tts(text):
    print("Start chuyển văn bản thành giọng nói")
    voice = "vi-VN-HoaiMyNeural"
    tts = edge_tts.Communicate(text, voice)
    await tts.save("output.mp3")
    print("End chuyển văn bản thành giọng nói")


@app.route("/")
def home():
    content = asyncio.run(getNewPost24h())
    contentEdit = asyncio.run(editContent(content))
    asyncio.run(tts(contentEdit))
    createVideo()
    return "Tạo thành công"

@app.route("/view")
def view():
    return send_file("output_video.mp4", mimetype="video/mp4")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
