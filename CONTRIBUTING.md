# 貢獻指南

感謝你考慮為本專案（本機 LLM 推論堆疊：vLLM + Flask gateway + Open WebUI）貢獻程式碼。本文件說明如何準備開發環境、跑測試、以及送出 PR 前該做的檢查。

## 開發環境準備

- Python 版本：**3.12**
- gateway 原始碼在 `gateway/app/`，測試在 `gateway/tests/`。

```bash
cd gateway
python -m venv .venv                 # 若尚未建立虛擬環境
# Windows: .venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
pip install -r requirements-dev.txt  # 內含 runtime 依賴（Flask/requests/waitress）+ pytest
```

## 在本機跑測試

測試分兩類，設定在 `gateway/pytest.ini`（`testpaths = tests`，並定義了 `smoke` marker）：

- **單元測試**（`gateway/tests/test_llm_client.py`、`gateway/tests/test_routes.py`）：純 mock，不需要網路或真實服務，也是 CI 會跑的測試：

  ```bash
  cd gateway
  pytest -m "not smoke"
  ```

- **端對端冒煙測試**（`gateway/tests/test_smoke.py`，全檔標了 `pytest.mark.smoke`）：需要 gateway 與 vLLM 都真的啟動才能跑；沒偵測到服務時會自動 skip。先啟動服務（見下一節），再執行：

  ```bash
  cd gateway
  pytest -m smoke
  ```

## 用 compose 起 CPU 版做開發

沒有 NVIDIA GPU 的開發環境，可以用 CPU 版 compose 起 `vllm` 與 `open-webui`：

```bash
cp .env.example .env          # Windows: Copy-Item .env.example .env
docker compose -f docker-compose.cpu.yml up -d
```

gateway 目前不在 compose 網路內，需另外用本機 `.venv` 啟動（跑在宿主機上，才能被 Open WebUI 透過 `host.docker.internal` 連到）。有 NVIDIA GPU 的環境則改用 `docker-compose.gpu.yml`，用法相同。

Windows 使用者也可以參考 `scripts\start-stack.ps1` 一次啟動整組堆疊。

## 分支與 commit 訊息慣例

- 從 `main` 切出功能分支，命名建議：`feat/<簡述>`、`fix/<簡述>`、`docs/<簡述>`、`chore/<簡述>`。
- commit 訊息第一行簡短說明「做了什麼」，動詞開頭（例如 `fix: 修正 gateway 逾時未正確回傳 504`）；需要時在空一行後補充「為什麼」。
- 每個 commit 盡量聚焦單一變更，避免把不相關的改動混在一起。

## 送 PR 前的自我檢查清單

送出 PR 前請確認：

- [ ] 本機執行 `pytest -m "not smoke"`（於 `gateway` 目錄下）全數通過
- [ ] 若變更涉及 compose 設定，已用 `docker compose -f docker-compose.gpu.yml config -q` 與 `docker compose -f docker-compose.cpu.yml config -q` 驗證語法（記得先 `cp .env.example .env`）
- [ ] 若變更影響 gateway 的建置，已確認 `gateway/Dockerfile` 能正常建置
- [ ] 沒有夾帶不相關檔案（`.env`、`models/`、`logs/`、`.venv/` 等已在 `.gitignore` 中，正常不會被追蹤）
- [ ] PR 說明清楚（用 PR 模板即可），並確認 CI 的三個 job（`test`、`compose-validate`、`docker-build`）都是綠燈

## 回報 issue 時該附什麼資訊

請盡量用 issue 模板（Bug Report / Feature Request）建立 issue。回報錯誤時，請附上：

- 問題描述與重現步驟
- 預期行為 vs 實際行為
- 部署方式（GPU compose / CPU compose / Windows `start-stack.ps1` / 其他）
- 環境資訊：作業系統、`docker --version` 輸出、GPU 型號與 VRAM（若無 GPU 請註明）
- 相關 log（例如 `docker compose logs`、或 `logs/` 目錄下的 gateway log）

資訊越完整，越有機會被快速排查與修正。
