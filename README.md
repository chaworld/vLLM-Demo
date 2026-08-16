# vLLM-Demo 

以 Docker Compose 一鍵拉起的本機大語言模型服務:**vLLM** 負責推論、**Flask gateway** 提供可觀測、可重試的 OpenAI 相容介面、**Open WebUI** 提供瀏覽器聊天介面。


## 這是什麼

一套可以整組複製走的「本機 LLM 服務範本」。

**為什麼中間要多一層 gateway?** 直接把 vLLM 端點對外開放也能用,但少了維運需要的東西。這層 Flask + waitress 代理補上:

- **健康探針分層** — `/healthz` 只確認 gateway 行程存活(不觸碰上游),`/readyz` 會實打上游 `/models` 確認整條推論鏈可用。兩者語義不同,才能讓 compose 的 `depends_on: service_healthy` 與外部監控各取所需。
- **逾時與重試** — 連線/讀取逾時分開設定(`LLM_CONNECT_TIMEOUT` / `LLM_READ_TIMEOUT`),並對 429/500/502/503/504 做指數退避重試,避免上游暖機期間的瞬斷直接變成使用者錯誤。
- **執行期指標** — `/metrics` 輸出請求量、失敗數、延遲 p50/p95/max 與累計 prompt/completion token,不必額外接 Prometheus 就能看到基本水位。
- **結構化日誌** — 每筆請求配發 `request_id` 並回寫到 `X-Request-ID` 標頭,以 JSON Lines 落地到 `logs/gateway/`,可用同一個 ID 串起 gateway 與容器日誌。
- **回應正規化** — 統一相容 `max_tokens` / `max_completion_tokens` 兩種欄位、把上游的一次性回應包裝成 OpenAI 格式的 SSE 串流,並在伺服器端固定關閉 thinking、清除殘留的推理內容,前端拿到的永遠是乾淨的最終答案。


| 服務 | 角色 | 宿主機預設網址 |
|---|---|---|
| `open-webui` | 瀏覽器聊天介面 | <http://localhost:3000> |
| `gateway` | OpenAI 相容代理層 | <http://localhost:8080/v1> |
| `vllm` | 推論引擎原始端點 | <http://localhost:8001/v1> |

## 系統需求

| 項目 | 需求 |
|---|---|
| **共通** | Docker Engine 24+ 或 Docker Desktop(含 Compose v2);約 15 GB 磁碟空間(vLLM 映像較大)+ 約 1.7 GB 模型權重;可連外網路 |
| **GPU 版**<br>`docker-compose.gpu.yml` | NVIDIA GPU 與對應驅動。**Linux 原生主機必須先安裝 [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)**,否則 compose 的 `devices: driver: nvidia` 保留區塊會失敗;Windows 11 + Docker Desktop(WSL2 後端)已內建 GPU 直通,不需另外安裝。顯存需求視參數而定,4 GB 等小顯存卡需調參(見[小顯存調參](#小顯存調參)) |
| **CPU 版**<br>`docker-compose.cpu.yml` | x86_64 主機保持 `VLLM_CPU_IMAGE_TAG=latest-x86_64`,macOS Apple Silicon 等 ARM 主機改為 `latest-arm64`;建議 8 GB 以上可用記憶體(`VLLM_MEMORY_LIMIT` 預設 `8g`)。純 CPU 推論明顯較慢,compose 已把 `start_period` 放寬到 180 秒、`LLM_READ_TIMEOUT` 放寬到 300 秒 |
| **開發(選用)** | Python 3.12,僅在宿主機跑測試或直接執行 gateway 時需要 |


## 致謝

本專案是把以下優秀的開源專案接起來的一層薄殼,實質工作都由它們完成:

- [vLLM](https://github.com/vllm-project/vllm) — 高吞吐的 LLM 推論與服務引擎,提供 OpenAI 相容 API([官方文件](https://docs.vllm.ai/))
- [Qwen](https://github.com/QwenLM/Qwen3) — 阿里巴巴通義千問團隊的開源模型系列;本堆疊使用 [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B)
- [Open WebUI](https://github.com/open-webui/open-webui) — 可自架、對 OpenAI 相容端點友善的網頁聊天介面([官方文件](https://docs.openwebui.com/))
