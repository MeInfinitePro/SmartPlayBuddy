# SmartPlayBuddy WebAPI 镜像：多阶段构建（前端 dist 编译 + Python 运行时）
# 构建上下文 = 项目根目录：docker build -f deploy/Dockerfile ..
# 注：不构建 wheel，直接 PYTHONPATH 运行 src，规避校园网下 pip build-isolation 的网络问题。

# ---------- 阶段一：构建 Vue 前端 ----------
FROM node:22-alpine AS webui
WORKDIR /webui
COPY web/frontend/package.json web/frontend/package-lock.json* ./
RUN npm ci
COPY web/frontend/ ./
RUN npm run build

# ---------- 阶段二：Python 运行时（仅共享依赖，无 Windows 驱动） ----------
FROM python:3.12-slim
WORKDIR /app

# 显式安装运行所需依赖（阿里云镜像；清华镜像对部分校园网返回 403）
RUN pip install --no-cache-dir \
      -i https://mirrors.aliyun.com/pypi/simple/ \
      "websockets>=12.0" keyring pydantic-settings \
      fastapi "uvicorn[standard]>=0.29"

COPY src ./src
ENV PYTHONPATH=/app/src

COPY web/backend ./web/backend
# 前端构建产物放到 app.py 约定的托管路径
COPY --from=webui /webui/dist ./web/frontend/dist

# 容器内监听 8765；对外是否可达由 compose 的 ports 决定（默认不发布）
EXPOSE 8765
CMD ["python", "web/backend/app.py", "--host", "0.0.0.0", "--port", "8765"]
