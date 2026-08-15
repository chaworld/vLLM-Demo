#!/usr/bin/env bash
# REST API 呼叫範例(Linux / macOS / Git Bash)。
# 用法:bash rest_api_examples.sh [gateway_base_url] [vllm_base_url]
set -euo pipefail

GATEWAY_URL="${1:-http://localhost:8080}"
VLLM_URL="${2:-http://localhost:8000}"
MODEL="${MODEL:-qwen3.5-0.8b}"

section() { printf '\n=== %s ===\n' "$1"; }

section "1. gateway 存活檢查"
curl -sS "${GATEWAY_URL}/healthz"; echo

section "2. gateway 就緒檢查(會實際打上游 vLLM)"
curl -sS "${GATEWAY_URL}/readyz"; echo

section "3. 可用模型清單"
curl -sS "${GATEWAY_URL}/v1/models"; echo

section "4. 對話補全(gateway 已強制關閉 thinking,不需自行帶參數)"
curl -sS "${GATEWAY_URL}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d @- <<JSON
{
  "model": "${MODEL}",
  "messages": [
    {"role": "system", "content": "你是一個以繁體中文回答的助理。"},
    {"role": "user", "content": "用一句話說明什麼是向量資料庫。"}
  ],
  "temperature": 0.3,
  "max_tokens": 256
}
JSON
echo

section "5. 串流格式回應(Open WebUI 使用的形式)"
curl -sS -N "${GATEWAY_URL}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"說「你好」兩個字\"}],\"stream\":true,\"max_tokens\":32}"
echo

section "6. 服務指標"
curl -sS "${GATEWAY_URL}/metrics"; echo

section "7. 直連 vLLM(繞過 gateway 時,必須自行帶 chat_template_kwargs 才能關閉 thinking)"
curl -sS "${VLLM_URL}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer EMPTY' \
  -d @- <<JSON
{
  "model": "${MODEL}",
  "messages": [{"role": "user", "content": "1 加 1 等於多少?只回答數字。"}],
  "max_tokens": 32,
  "chat_template_kwargs": {"enable_thinking": false}
}
JSON
echo
