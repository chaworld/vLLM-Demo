<#
預先下載 Qwen3.5-0.8B 權重到 ./models(Windows PowerShell 7+)。
非必要步驟:vLLM 首次啟動時也會自動下載,此腳本用於先把權重備妥再啟動服務。
用法:pwsh -File scripts/download_model.ps1
#>
param(
    [string]$ModelRepo = $(if ($env:MODEL_REPO) { $env:MODEL_REPO } else { 'Qwen/Qwen3.5-0.8B' })
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$modelsDir = Join-Path $projectRoot 'models'
New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null

Write-Host "下載 $ModelRepo 到 $modelsDir ..." -ForegroundColor Cyan

# 以一次性容器執行下載,宿主機不需安裝 Python 或 huggingface_hub
docker run --rm `
    -v "${modelsDir}:/models" `
    -v "${PSScriptRoot}:/scripts:ro" `
    -e MODEL_REPO=$ModelRepo `
    -e HF_HOME=/models `
    -e HUGGING_FACE_HUB_TOKEN=$env:HUGGING_FACE_HUB_TOKEN `
    python:3.12-slim `
    sh -c 'pip install --quiet --no-cache-dir "huggingface_hub>=0.26" && python /scripts/download_model.py'

if ($LASTEXITCODE -ne 0) {
    throw "下載失敗,結束碼 $LASTEXITCODE"
}
Write-Host '完成。' -ForegroundColor Green
