FROM python:3.12-slim
 
# 安装 Node.js 20
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*
 
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
 
COPY . .
 
CMD ["python3", "server.py"]
 
