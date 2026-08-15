#!/usr/bin/env bash
# 預先下載 Qwen3.5-0.8B 權重到 ./models(Linux / macOS)。
# 非必要步驟:vLLM 首次啟動時也會自動下載,此腳本用於先把權重備妥再啟動服務。
# 用法:bash scripts/download_model.sh
set -euo pipefail

MODEL_REPO="${MODEL_REPO:-Qwen/Qwen3.5-0.8B}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$(dirname "${SCRIPT_DIR}")/models"

mkdir -p "${MODELS_DIR}"
echo "下載 ${MODEL_REPO} 到 ${MODELS_DIR} ..."

# 以一次性容器執行下載,宿主機不需安裝 Python 或 huggingface_hub
docker run --rm \
    -v "${MODELS_DIR}:/models" \
    -v "${SCRIPT_DIR}:/scripts:ro" \
    -e MODEL_REPO="${MODEL_REPO}" \
    -e HF_HOME=/models \
    -e HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-}" \
    python:3.12-slim \
    sh -c 'pip install --quiet --no-cache-dir "huggingface_hub>=0.26" && python /scripts/download_model.py'

echo '完成。'
