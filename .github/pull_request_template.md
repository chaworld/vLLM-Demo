## 變更摘要

<!-- 簡述這個 PR 做了什麼、為什麼需要這個變更 -->

## 變更類型

- [ ] 錯誤修正 (bug fix)
- [ ] 新功能 (feature)
- [ ] 文件更新 (documentation)
- [ ] 重構 / 內部調整 (refactor，不影響外部行為)
- [ ] 其他（請說明）

## 測試方式

<!-- 說明你如何驗證這個變更，例如：
- 執行了 `pytest -m "not smoke"` 並全數通過
- 本機以 docker-compose.cpu.yml 起服務，手動打了 /v1/chat/completions 驗證
- 執行了端對端 `pytest -m smoke`（需先啟動 gateway + vLLM）
-->

## 檢查清單

- [ ] 已在本機執行 `pytest -m "not smoke"` 並通過
- [ ] 若變更影響行為，已視需要新增或更新對應測試
- [ ] 若變更影響使用方式或設定，已同步更新相關文件（README / CONTRIBUTING 等）
- [ ] 未包含與此變更無關的檔案（例如個人設定、暫存檔、`.env`、`models/`、`logs/`）
- [ ] CI 三個 job（test、compose-validate、docker-build）皆為綠燈
