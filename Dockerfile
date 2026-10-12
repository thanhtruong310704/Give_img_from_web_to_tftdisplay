FROM python:3.11-slim

# Ngăn Python tạo bytecode và đệm stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Cài đặt thư viện phụ thuộc
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy mã nguồn
COPY . .

# Mặc định port 8000, hỗ trợ override bằng biến môi trường $PORT khi deploy
ENV PORT=8000
EXPOSE 8000

# Chạy ứng dụng thông qua shell để resolve $PORT linh hoạt
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
