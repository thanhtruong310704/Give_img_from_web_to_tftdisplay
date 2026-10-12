import os
import io
import asyncio
from typing import List
from contextlib import asynccontextmanager
from PIL import Image, ImageSequence
import paho.mqtt.client as mqtt
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse

# Cấu hình từ biến môi trường
TFT_WIDTH = int(os.getenv("TFT_WIDTH", "240"))
TFT_HEIGHT = int(os.getenv("TFT_HEIGHT", "320"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "65"))

MQTT_BROKER = os.getenv("MQTT_BROKER", "broker.emqx.io")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "esp32_s3_tft_display_channel/frame")

# Khởi tạo MQTT Client
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
current_stream_task: asyncio.Task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động kết nối MQTT khi server bật
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
        print(f"[+] Đã kết nối MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
    except Exception as e:
        print(f"[-] Lỗi kết nối MQTT: {e}")
    yield
    # Dọn dẹp tài nguyên khi tắt server
    global current_stream_task
    if current_stream_task and not current_stream_task.done():
        current_stream_task.cancel()
    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    print("[*] Đã ngắt kết nối MQTT an toàn.")

app = FastAPI(title="ESP32 TFT Streamer", lifespan=lifespan)

def process_frame(img: Image.Image, mode: str = "crop") -> bytes:
    """
    Xử lý frame:
    - mode='crop': Center crop (phóng to phủ kín 240x320, không viền đen)
    - mode='letterbox': Giữ nguyên tỉ lệ gốc, thêm dải đen (letterbox)
    - mode='direct': Ảnh đã được crop chuẩn từ client (chỉ cần resize đúng kích thước nếu cần)
    """
    img = img.convert("RGB")
    orig_w, orig_h = img.size

    if mode == "letterbox":
        scale = min(TFT_WIDTH / orig_w, TFT_HEIGHT / orig_h)
        new_w, new_h = max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (TFT_WIDTH, TFT_HEIGHT), (0, 0, 0))
        canvas.paste(resized, ((TFT_WIDTH - new_w) // 2, (TFT_HEIGHT - new_h) // 2))
        final_img = canvas
    elif mode == "crop":
        scale = max(TFT_WIDTH / orig_w, TFT_HEIGHT / orig_h)
        new_w, new_h = max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
        resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - TFT_WIDTH) // 2
        top = (new_h - TFT_HEIGHT) // 2
        final_img = resized.crop((left, top, left + TFT_WIDTH, top + TFT_HEIGHT))
    else:  # 'direct'
        if (orig_w, orig_h) != (TFT_WIDTH, TFT_HEIGHT):
            final_img = img.resize((TFT_WIDTH, TFT_HEIGHT), Image.Resampling.LANCZOS)
        else:
            final_img = img

    buf = io.BytesIO()
    final_img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()

async def loop_animation(frames: List[bytes], durations: List[float]):
    """Phát lặp vô tận từng frame của GIF qua MQTT"""
    try:
        while True:
            for frame_data, delay_sec in zip(frames, durations):
                mqtt_client.publish(MQTT_TOPIC, frame_data, qos=0)
                await asyncio.sleep(max(delay_sec, 0.07))
    except asyncio.CancelledError:
        pass

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <title>ESP32 TFT Studio & Streamer</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <!-- Cropper.js CDN -->
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.13/cropper.min.css"/>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.5.13/cropper.min.js"></script>
        <style>
            :root {
                --primary: #38bdf8;
                --success: #10b981;
                --bg: #0b0f19;
                --card-bg: #1e293b;
                --border: #334155;
            }
            body {
                font-family: system-ui, -apple-system, sans-serif;
                max-width: 620px;
                margin: 20px auto;
                padding: 15px;
                background: var(--bg);
                color: #f8fafc;
            }
            .card {
                background: var(--card-bg);
                padding: 24px;
                border-radius: 16px;
                border: 1px solid var(--border);
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            }
            h2 { margin: 0 0 16px 0; color: var(--primary); text-align: center; font-size: 22px; }
            .btn {
                background: var(--success);
                color: #fff;
                border: none;
                padding: 12px 18px;
                border-radius: 8px;
                font-size: 15px;
                font-weight: 600;
                cursor: pointer;
                transition: 0.2s;
                width: 100%;
            }
            .btn:hover { background: #059669; }
            .btn-secondary {
                background: #475569;
                padding: 8px 12px;
                font-size: 13px;
                width: auto;
            }
            .btn-secondary:hover { background: #64748b; }
            .mode-selector {
                display: flex;
                gap: 10px;
                margin: 15px 0;
            }
            .mode-option {
                flex: 1;
                text-align: center;
                background: #0f172a;
                padding: 10px;
                border-radius: 8px;
                border: 2px solid transparent;
                cursor: pointer;
                font-size: 13px;
            }
            .mode-option.active {
                border-color: var(--primary);
                color: var(--primary);
                font-weight: bold;
            }
            .cropper-box {
                max-height: 400px;
                background: #000;
                border-radius: 8px;
                overflow: hidden;
                margin: 15px 0;
                display: none;
            }
            .cropper-box img { max-width: 100%; }
            .toolbar {
                display: flex;
                gap: 8px;
                justify-content: center;
                margin-bottom: 15px;
            }
            .preview-container {
                margin: 15px auto;
                width: 240px;
                height: 320px;
                background: #000;
                border: 4px solid #475569;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                overflow: hidden;
                box-shadow: 0 0 15px rgba(56, 189, 248, 0.2);
            }
            .preview-container img {
                width: 100%;
                height: 100%;
                object-fit: contain;
                display: none;
            }
            #status { margin-top: 15px; text-align: center; font-size: 14px; color: var(--primary); font-weight: 500; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>ESP32-S3 TFT Display Studio</h2>
            
            <input type="file" id="fileInput" accept="image/*,.gif" style="margin-bottom:12px; width:100%; color:#94a3b8;" />

            <!-- Chế độ xử lý ảnh -->
            <div class="mode-selector" id="modeSelector">
                <div class="mode-option active" data-mode="crop">✂️ Center Crop<br><small>(Lấp đầy màn hình)</small></div>
                <div class="mode-option" data-mode="letterbox">🔲 Letterbox<br><small>(Viền đen giữ tỉ lệ)</small></div>
                <div class="mode-option" data-mode="custom">📐 Tùy chỉnh Crop<br><small>(Kéo thả khung)</small></div>
            </div>

            <!-- Vùng Crop tương tác (Cropper.js) cho ảnh tĩnh -->
            <div class="cropper-box" id="cropperContainer">
                <img id="cropperImage" alt="Editor" />
            </div>

            <div class="toolbar" id="cropperToolbar" style="display:none;">
                <button type="button" class="btn btn-secondary" onclick="rotate(-90)">↺ Xoay trái</button>
                <button type="button" class="btn btn-secondary" onclick="rotate(90)">↻ Xoay phải</button>
                <button type="button" class="btn btn-secondary" onclick="resetCrop()">⟲ Mặc định</button>
            </div>

            <!-- Khung Preview giả lập TFT 240x320 -->
            <div class="preview-container" id="tftPreviewBox">
                <span id="placeholderText" style="color:#64748b; font-size:13px; text-align:center; padding:10px;">
                    Màn hình TFT Dọc (240x320)
                </span>
                <img id="imagePreview" alt="Preview" />
            </div>

            <button type="button" class="btn" id="sendBtn">🚀 Gửi Lên Màn Hình TFT</button>
            <div id="status">Chọn ảnh tĩnh hoặc ảnh GIF để bắt đầu</div>
        </div>

        <script>
            let cropper = null;
            let currentFile = null;
            let isGif = false;
            let currentMode = 'crop';

            const fileInput = document.getElementById('fileInput');
            const cropperContainer = document.getElementById('cropperContainer');
            const cropperImage = document.getElementById('cropperImage');
            const cropperToolbar = document.getElementById('cropperToolbar');
            const imagePreview = document.getElementById('imagePreview');
            const placeholderText = document.getElementById('placeholderText');
            const tftPreviewBox = document.getElementById('tftPreviewBox');
            const statusDiv = document.getElementById('status');
            const sendBtn = document.getElementById('sendBtn');

            // Xử lý chọn chế độ
            document.querySelectorAll('.mode-option').forEach(opt => {
                opt.addEventListener('click', () => {
                    document.querySelectorAll('.mode-option').forEach(o => o.classList.remove('active'));
                    opt.classList.add('active');
                    currentMode = opt.dataset.mode;
                    updateUIByMode();
                });
            });

            function updateUIByMode() {
                if (isGif) {
                    // GIF không hỗ trợ interactive crop từng frame
                    if (currentMode === 'custom') currentMode = 'crop';
                    cropperContainer.style.display = 'none';
                    cropperToolbar.style.display = 'none';
                    tftPreviewBox.style.display = 'flex';
                    imagePreview.style.objectFit = (currentMode === 'crop') ? 'cover' : 'contain';
                    return;
                }

                if (currentMode === 'custom' && currentFile) {
                    cropperContainer.style.display = 'block';
                    cropperToolbar.style.display = 'flex';
                    tftPreviewBox.style.display = 'none';
                    initCropper();
                } else {
                    destroyCropper();
                    cropperContainer.style.display = 'none';
                    cropperToolbar.style.display = 'none';
                    tftPreviewBox.style.display = 'flex';
                    if (currentFile) {
                        imagePreview.style.objectFit = (currentMode === 'crop') ? 'cover' : 'contain';
                    }
                }
            }

            fileInput.onchange = (e) => {
                const file = e.target.files[0];
                if (!file) return;

                currentFile = file;
                isGif = file.name.toLowerCase().endsWith('.gif');
                const reader = new FileReader();

                reader.onload = (event) => {
                    const dataUrl = event.target.result;
                    imagePreview.src = dataUrl;
                    imagePreview.style.display = 'block';
                    placeholderText.style.display = 'none';
                    cropperImage.src = dataUrl;

                    if (isGif) {
                        statusDiv.innerText = "Đã chọn ảnh GIF động.";
                        document.querySelector('[data-mode="custom"]').style.opacity = '0.4';
                    } else {
                        statusDiv.innerText = "Đã chọn ảnh tĩnh. Bạn có thể chọn chế độ crop.";
                        document.querySelector('[data-mode="custom"]').style.opacity = '1';
                    }
                    updateUIByMode();
                };
                reader.readAsDataURL(file);
            };

            function initCropper() {
                if (cropper) cropper.destroy();
                cropper = new Cropper(cropperImage, {
                    aspectRatio: 240 / 320,
                    viewMode: 1,
                    autoCropArea: 1,
                    background: false,
                    responsive: true
                });
            }

            function destroyCropper() {
                if (cropper) {
                    cropper.destroy();
                    cropper = null;
                }
            }

            function rotate(deg) { if (cropper) cropper.rotate(deg); }
            function resetCrop() { if (cropper) cropper.reset(); }

            sendBtn.onclick = async () => {
                if (!currentFile) {
                    alert("Vui lòng chọn ảnh trước!");
                    return;
                }

                statusDiv.innerText = "⏳ Đang xử lý và gửi dữ liệu...";
                const formData = new FormData();

                if (!isGif && currentMode === 'custom' && cropper) {
                    // Xuất ảnh từ Cropper canvas chuẩn 240x320
                    const canvas = cropper.getCroppedCanvas({ width: 240, height: 320 });
                    canvas.toBlob(async (blob) => {
                        formData.append('file', blob, 'cropped.jpg');
                        formData.append('mode', 'direct');
                        await uploadData(formData);
                    }, 'image/jpeg', 0.9);
                } else {
                    formData.append('file', currentFile);
                    formData.append('mode', currentMode);
                    await uploadData(formData);
                }
            };

            async function uploadData(formData) {
                try {
                    const res = await fetch('/upload', { method: 'POST', body: formData });
                    const data = await res.json();
                    statusDiv.innerText = "✅ " + data.message;
                } catch (err) {
                    statusDiv.innerText = "❌ Lỗi kết nối khi gửi dữ liệu!";
                }
            }
        </script>
    </body>
    </html>
    """

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), mode: str = Form("crop")):
    global current_stream_task

    # Dừng task stream cũ nếu đang chạy
    if current_stream_task and not current_stream_task.done():
        current_stream_task.cancel()
        try:
            await current_stream_task
        except asyncio.CancelledError:
            pass

    file_bytes = await file.read()
    img = Image.open(io.BytesIO(file_bytes))

    is_animated = getattr(img, "is_animated", False) and img.n_frames > 1

    if is_animated:
        frames: List[bytes] = []
        durations: List[float] = []

        print(f"[*] Đang xử lý GIF ({img.n_frames} frames, chế độ: {mode})...")
        for frame in ImageSequence.Iterator(img):
            frame_bytes = process_frame(frame, mode=mode)
            frames.append(frame_bytes)

            dur_ms = frame.info.get("duration", 100)
            if dur_ms < 20:
                dur_ms = 100
            durations.append(dur_ms / 1000.0)

        current_stream_task = asyncio.create_task(loop_animation(frames, durations))
        print(f"[+] Bắt đầu stream GIF lặp lại ({len(frames)} frames)!")
        return {"status": "success", "message": f"Đang phát GIF ({len(frames)} frames) liên tục trên TFT!"}

    else:
        jpeg_data = process_frame(img, mode=mode)
        mqtt_client.publish(MQTT_TOPIC, jpeg_data, qos=0)
        print(f"[+] Đã gửi 1 ảnh ({len(jpeg_data)} bytes) qua topic: {MQTT_TOPIC}")
        return {"status": "success", "message": f"Ảnh tĩnh đã gửi thành công ({len(jpeg_data)} bytes)!"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
