# syntax=docker/dockerfile:1

# ---- 构建阶段：只在这里使用 uv，安装依赖到 /app/.venv ----
FROM python:3.12.14-slim-bookworm AS builder
# uv 版本与开发机一致（uv --version = 0.12.5），保证 uv.lock 的解析行为相同。
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /bin/uv
WORKDIR /app
# 预编译 .pyc 让启动更快；copy 模式避免跨层硬链接失败；禁止 uv 自行下载 Python，只用镜像自带的。
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# 先只复制依赖清单：代码改动时这一层可以走缓存。
COPY pyproject.toml uv.lock ./
# --frozen：严格按 uv.lock 安装，不重新解析；--no-dev：不装 pytest。
RUN uv sync --frozen --no-dev

# ---- 运行阶段：不含 uv、构建缓存和测试 ----
FROM python:3.12.14-slim-bookworm
# 非 root 用户运行，固定 uid 便于核对挂载文件的权限。
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./
COPY finrag/ ./finrag/
COPY web/ ./web/
# 只复制清单；data/raw 和 data/index 体积大，由 compose 以只读卷挂载。
COPY data/manifest.json ./data/manifest.json

# PYTHONUNBUFFERED：日志即时输出到 docker logs；PYTHONDONTWRITEBYTECODE：运行时不写 .pyc（依赖的字节码已在构建阶段生成）。
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# 对话记录（SQLite）写在这里；compose 用命名卷挂载，首次挂载时会继承该目录的所有者。
RUN mkdir -p /app/data/state && chown app:app /app/data/state
USER app
EXPOSE 8000
# 直接用虚拟环境里的 python，启动时不联网、不同步依赖。
CMD ["/app/.venv/bin/python", "-m", "finrag.api"]
