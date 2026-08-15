# Flask gateway 映像;python:3.12-slim 官方映像同時提供 amd64 與 arm64,可跨平台建置
# 多階段建置:base(共用基礎層)→ dev(測試用,含 pytest)→ runtime(正式環境,不含 pytest)
# runtime 是檔案中「最後一個 stage」,因此 `docker build ./gateway`(不指定 --target)預設就會建出 runtime。
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_DIR=/var/log/gateway

WORKDIR /app

# 以非 root 身分執行,並預先建立日誌目錄的寫入權限
RUN useradd --create-home --uid 10001 gateway \
    && mkdir -p ${LOG_DIR} \
    && chown -R gateway:gateway ${LOG_DIR}

# app 程式碼是 runtime / dev 共用的部分,放在 base 只複製一次
COPY app ./app

EXPOSE 8080

# python:3.12-slim 沒有 curl/wget,改用內建 urllib 探測 /healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).status == 200 else 1)"

CMD ["python", "-m", "app.main"]

# ---------- dev:base 之上安裝 requirements-dev.txt(含 pytest)與測試檔,供 unit-test / smoke-test service 使用 ----------
# 注意:dev 必須 FROM base(不可 FROM runtime),因為 runtime 要放在檔案最後一個 stage 的位置,
# dev 不能排在它後面,否則會變成不指定 --target 時的預設建置目標。
FROM base AS dev

# requirements-dev.txt 內以 -r requirements.txt 引用基礎套件清單,兩個檔案都要複製
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY pytest.ini ./
COPY tests ./tests
RUN chown -R gateway:gateway /app

USER gateway

# ---------- runtime:base 之上僅安裝 requirements.txt(不含 pytest)----------
# 檔案中最後一個 stage,不指定 --target 時的預設建置目標。
FROM base AS runtime

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN chown -R gateway:gateway /app

USER gateway
