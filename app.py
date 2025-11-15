from flask import Flask, send_file, jsonify
import requests
import os
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

def ffmpeg_can_read(path):
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0

async def createVideo():
    print("Start video")

    IMAGE_FOLDER = "images"
    AUDIO_PATH = "output.mp3"
    OUTPUT_PATH = "output_video.mp4"
    MIN_DURATION = 0.10   # tối thiểu 0.1 giây

    # ===== Load ảnh =====
    exts = ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp"]
    images = []
    for e in exts:
        images += glob.glob(os.path.join(IMAGE_FOLDER, e))

    images = sorted(images, key=os.path.getctime)

    if not images:
        raise ValueError("Không có ảnh!")

    # ===== Kiểm tra ảnh hỏng =====
    valid_imgs = []
    for img in images:
        if ffmpeg_can_read(img):
            valid_imgs.append(img)
        else:
            print("Ảnh lỗi (bỏ qua):", img)

    if not valid_imgs:
        raise ValueError("Không ảnh nào hợp lệ!")

    # ===== Lấy độ dài âm thanh =====
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", AUDIO_PATH],
        capture_output=True, text=True
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])

    per_img = duration / len(valid_imgs)

    # tránh duration nhỏ gây frame duplicate
    if per_img < MIN_DURATION:
        print("Duration quá nhỏ, set lại:", MIN_DURATION)
        per_img = MIN_DURATION

    # ===== Tạo list.txt =====
    list_path = "list.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for img in valid_imgs:
            img_rel = img.replace("\\", "/")
            f.write(f"file '{img_rel}'\n")
            f.write(f"duration {per_img}\n")

        last = valid_imgs[-1].replace("\\", "/")
        f.write(f"file '{last}'\n")

    print("list.txt OK")

    # ===== Tạo video =====
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-i", AUDIO_PATH,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        OUTPUT_PATH
    ]

    subprocess.run(cmd, check=True)
    print("DONE:", OUTPUT_PATH)

async def getNewPost24h():
    print("Start lấy bài viết mới")
    rss_url = "https://cdn.24h.com.vn/upload/rss/anninhhinhsu.rss"
    google_script_url = 'https://script.google.com/macros/s/AKfycbzpFYZwnJXnOSkoimpjUJzSuz3xH88Tfn9t9-BNjvfb4H1SXQ8XzfLjgr0dWFHoe8Zt/exec'
    save_folder = "images"

    if os.path.exists(save_folder):
        shutil.rmtree(save_folder)
        print(f"🧹 Đã xóa thư mục cũ: {save_folder}")
    os.makedirs(save_folder)

    # --- Hàm tải ảnh ---
    def download_image(url, prefix="img", width=1080, height=1920, save_folder="images"):
        try:
            if not url or not url.startswith("http"):
                return None
            os.makedirs(save_folder, exist_ok=True)
            ext = os.path.splitext(url.split("?")[0])[-1].lower()
            if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
                ext = ".jpg"
            filename = f"{prefix}_{hashlib.md5(url.encode()).hexdigest()[:10]}{ext}"
            filepath = os.path.join(save_folder, filename)
            if os.path.exists(filepath):
                return filepath
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                print(f"⚠️ Lỗi tải ảnh: {url}")
                return None
            img_bytes = io.BytesIO(response.content)
            codec = "mjpeg" if ext in [".jpg", ".jpeg"] else ext.replace(".", "")
            cmd = [
                "ffmpeg", "-y", "-f", "image2pipe", "-vcodec", codec, "-i", "pipe:0",
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
                "-frames:v", "1", filepath
            ]
            subprocess.run(cmd, input=img_bytes.read(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            if os.path.exists(filepath):
                print(f"✅ Đã tải và resize (FFmpeg): {filename}")
                return filepath
        except subprocess.CalledProcessError as e:
            print(f"❌ FFmpeg lỗi khi xử lý {url}:\n{e.stderr.decode(errors='ignore')}")
        except Exception as e:
            print(f"❌ Lỗi khi xử lý ảnh {url}: {e}")
        return None

    # --- Lấy dữ liệu Google Sheet ---
    r = requests.get(google_script_url)
    try:
        dataInFiles = r.json()
        if not isinstance(dataInFiles, list):
            print("⚠️ Dữ liệu trả về không phải dạng list JSON, đặt giá trị mặc định rỗng.")
            dataInFiles = []
    except Exception as e:
        print(f"⚠️ Không thể parse JSON từ Google Script: {e}")
        print("Phản hồi thực tế:", r.text[:500])
        dataInFiles = []

    titles_in_sheet = [x.get("title", "") for x in dataInFiles]

    # --- Đọc RSS ---
    feed = feedparser.parse(rss_url)
    contentNewPost = ""
    for entry in feed.entries:
        title = entry.title
        link = entry.link
        if title in titles_in_sheet:
            continue

        image_url = None
        if 'media_content' in entry and len(entry.media_content) > 0:
            image_url = entry.media_content[0]['url']
        else:
            match = re.search(r'<img[^>]+src="([^">]+)"', entry.summary)
            if match:
                image_url = match.group(1)

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

        newData = {
            "title": title,
            "link": link,
            "image": image_url,
            "content": content_text
        }

        contentNewPost = content_text
        try:
            response = requests.post(google_script_url, json=newData)
            print("📤 Gửi dữ liệu lên Google Sheet:", response.status_code)
        except Exception as e:
            print(f"⚠️ Lỗi khi gửi dữ liệu lên Google Sheet: {e}")

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
    return "Chào Mừng"

@app.route("/create")
def create():
    content = asyncio.run(getNewPost24h())
    contentEdit = asyncio.run(editContent(content))
    asyncio.run(tts(contentEdit))
    asyncio.run(createVideo())
    return "Tạo thành công"

@app.route("/view")
def view():
    return send_file("output_video.mp4", mimetype="video/mp4")

@app.route("/check_list")
def check_list():
    # Thư mục tạo list.txt
    cwd = os.getcwd()
    list_path = os.path.join(cwd, "list.txt")
    
    # Thử tạo file test
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            f.write("file 'test.jpg'\n")
            f.write("duration 1\n")
        exists = os.path.exists(list_path)
        files_in_cwd = os.listdir(cwd)
        return jsonify({
            "cwd": cwd,
            "list_path": list_path,
            "list_exists": exists,
            "files_in_cwd": files_in_cwd
        })
    except Exception as e:
        return jsonify({
            "error": str(e),
            "cwd": cwd
        })

@app.route("/read_list")
def read_list():
    cwd = os.getcwd()
    list_path = os.path.join(cwd, "list.txt")
    # Kiểm tra file có tồn tại không
    if not os.path.exists(list_path):
        return jsonify({"error": "File list.txt không tồn tại!"})

    # Đọc file
    try:
        with open(list_path, "r", encoding="utf-8") as f:
            content = f.read()  # đọc toàn bộ file
        lines = content.splitlines()  # tách thành từng dòng
        return jsonify({
            "list_path": os.path.abspath(list_path),
            "lines": lines,
            "line_count": len(lines)
        })
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
