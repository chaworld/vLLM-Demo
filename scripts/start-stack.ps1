<#
.SYNOPSIS
    一鍵啟動 qwen3.5-0.8b 推論堆疊:Docker Desktop → 環境修復 → vLLM → Flask gateway
    →(可選)Open WebUI。每次重開機後直接執行本腳本即可,不需手動記憶各項啟動指令。

.DESCRIPTION
    流程:
      1. 確認 Docker Desktop 是否在跑,沒跑就嘗試啟動並輪詢等待 dockerd 就緒。
      2. 呼叫 scripts\fix-docker-env.ps1 施加 /run/user/0 與 bind mount 兩項修復。
      3. docker compose -f docker-compose.gpu.yml up -d vllm 啟動 vLLM。
      4. 輪詢等待 vLLM 容器變為 healthy(冷啟動需 170-260 秒,逾時設 420 秒)。
      5. 以專案內 .venv 背景啟動 Flask gateway(不是容器)。
      6. 輪詢等待 gateway /healthz 回應 200。
      7. 若指定 -WithOpenWebUI,以 docker compose up -d open-webui 啟動(或重用既有的)
         Open WebUI 容器,並輪詢等待其變為 healthy(逾時 120 秒)。
      8. 印出各服務的網址與健康狀態總覽表。

    任何一步失敗都會立即停止,並明確回報是哪一步、失敗原因、建議的下一步。

.PARAMETER WithOpenWebUI
    是否一併啟動 Open WebUI 容器。預設不啟動。

.PARAMETER GatewayHost
    Gateway(waitress)監聽的網卡位址。預設 127.0.0.1(僅本機可連,較安全)。
    若指定 -WithOpenWebUI 且未明確指定本參數,會自動改為 0.0.0.0,
    讓 Open WebUI 容器能透過 host.docker.internal 連到 gateway。
    警告:0.0.0.0 會讓 8080 埠對區域網路開放,而 gateway 本身沒有任何認證機制。

.EXAMPLE
    pwsh -File scripts\start-stack.ps1
    只啟動 vLLM + gateway,gateway 只綁 127.0.0.1(本機專用,最安全)。

.EXAMPLE
    pwsh -File scripts\start-stack.ps1 -WithOpenWebUI
    啟動 vLLM + gateway + Open WebUI,gateway 自動改綁 0.0.0.0。

.EXAMPLE
    pwsh -File scripts\start-stack.ps1 -GatewayHost 0.0.0.0
    不啟動 Open WebUI,但仍手動把 gateway 綁到 0.0.0.0(例如要給同網段其他機器測試)。
#>
[CmdletBinding()]
param(
    [switch]$WithOpenWebUI,
    [string]$GatewayHost = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $RepoRoot 'docker-compose.gpu.yml'
$FixScript = Join-Path $PSScriptRoot 'fix-docker-env.ps1'
$EnvFile = Join-Path $RepoRoot '.env'

function Write-Step { param([string]$Message) Write-Host ""; Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Info { param([string]$Message) Write-Host "    $Message" -ForegroundColor Gray }
function Write-Ok   { param([string]$Message) Write-Host "    [OK] $Message" -ForegroundColor Green }

function Stop-WithError {
    param(
        [Parameter(Mandatory)][string]$Step,
        [Parameter(Mandatory)][string]$Reason,
        [Parameter(Mandatory)][string]$NextAction
    )
    Write-Host ""
    Write-Host "===== 啟動流程中止 =====" -ForegroundColor Red
    Write-Host "失敗步驟:$Step" -ForegroundColor Red
    Write-Host "原因:$Reason" -ForegroundColor Red
    Write-Host "建議下一步:$NextAction" -ForegroundColor Yellow
    exit 1
}

function Test-UrlHealthy {
    param([string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) { return @{ Healthy = $true; Detail = "健康(200)" } }
        return @{ Healthy = $false; Detail = "異常($($resp.StatusCode))" }
    } catch {
        return @{ Healthy = $false; Detail = '無法連線' }
    }
}

function Get-DotEnvValue {
    # 從 .env 讀單一 KEY 的值;找不到檔案或找不到 KEY 就回傳預設值,不寫死埠號
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Key,
        [string]$Default = ''
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $Default }
    $line = Get-Content -LiteralPath $Path | Where-Object { $_ -match "^\s*$Key\s*=" } | Select-Object -Last 1
    if (-not $line) { return $Default }
    $value = ($line -split '=', 2)[1].Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

# vLLM 對外埠號一律從 .env 的 VLLM_PORT 讀取,讀不到才退回 compose 預設值(8000)
$VllmPort = Get-DotEnvValue -Path $EnvFile -Key 'VLLM_PORT' -Default '8000'

if ($WithOpenWebUI -and -not $PSBoundParameters.ContainsKey('GatewayHost')) {
    $GatewayHost = '0.0.0.0'
    Write-Host ""
    Write-Host "警告:已指定 -WithOpenWebUI,GatewayHost 自動改為 0.0.0.0。" -ForegroundColor Yellow
    Write-Host "      這會讓 gateway 的 8080 埠對區域網路開放,且 gateway 沒有任何認證機制,請留意網路環境安全性。" -ForegroundColor Yellow
}

Write-Host "===== qwen3.5-0.8b 推論堆疊啟動流程 =====" -ForegroundColor Cyan
Write-Info "專案目錄:$RepoRoot"
Write-Info "vLLM 對外埠號:$VllmPort(來源:.env 的 VLLM_PORT,讀不到則用預設 8000)"
Write-Info "Gateway 監聽位址:$($GatewayHost):8080"
Write-Info "啟動 Open WebUI:$WithOpenWebUI"

# ---------- 步驟 1/8:確認 Docker Desktop 是否在跑 ----------
Write-Step "步驟 1/8:確認 Docker Desktop 是否在執行"
docker info *>$null
if ($LASTEXITCODE -ne 0) {
    Write-Info "Docker Desktop 未回應,嘗試啟動..."
    $dockerDesktopExe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    $started = $false
    if (Test-Path -LiteralPath $dockerDesktopExe) {
        try {
            Start-Process -FilePath $dockerDesktopExe | Out-Null
            $started = $true
            Write-Info "已透過 Docker Desktop.exe 送出啟動請求"
        } catch {
            Write-Info "Start-Process 啟動失敗:$($_.Exception.Message)"
        }
    }
    if (-not $started) {
        Write-Info "找不到 Docker Desktop.exe 或啟動失敗,改用 'docker desktop start' 指令..."
        docker desktop start *>$null
        if ($LASTEXITCODE -eq 0) {
            $started = $true
            Write-Info "已透過 'docker desktop start' 送出啟動請求"
        }
    }
    if (-not $started) {
        Stop-WithError -Step "1/8 啟動 Docker Desktop" `
            -Reason "Start-Process 開啟 Docker Desktop.exe 與 'docker desktop start' 指令皆失敗" `
            -NextAction "手動開啟 Docker Desktop,確認可正常啟動後重新執行本腳本"
    }

    Write-Info "等待 dockerd 就緒(逾時 180 秒)..."
    $dockerReadyTimeoutSec = 180
    $elapsed = 0
    $dockerReady = $false
    while ($elapsed -lt $dockerReadyTimeoutSec) {
        docker info *>$null
        if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
        Start-Sleep -Seconds 5
        $elapsed += 5
        Write-Info "已等待 $elapsed 秒..."
    }
    if (-not $dockerReady) {
        Stop-WithError -Step "1/8 等待 Docker Desktop 就緒" `
            -Reason "等待 $dockerReadyTimeoutSec 秒後 dockerd 仍未回應" `
            -NextAction "檢查 Docker Desktop 是否卡在啟動畫面或需要手動處理更新/授權提示,處理後重新執行本腳本"
    }
    Write-Ok "Docker Desktop 已就緒(等待 $elapsed 秒)"
} else {
    Write-Ok "Docker Desktop 已在執行"
}

# ---------- 步驟 2/8:施加 Docker 環境修復 ----------
Write-Step "步驟 2/8:施加 Docker 環境修復(呼叫 fix-docker-env.ps1)"
& $FixScript
if ($LASTEXITCODE -ne 0) {
    Stop-WithError -Step "2/8 fix-docker-env.ps1" `
        -Reason "環境修復腳本回報失敗(exit code $LASTEXITCODE)" `
        -NextAction "手動執行 pwsh -File `"$FixScript`" -CheckOnly 查看細節"
}
Write-Ok "Docker 環境修復完成"

# ---------- 步驟 3/8:啟動 vLLM ----------
Write-Step "步驟 3/8:啟動 vLLM 容器(docker compose up -d vllm)"
docker compose -f $ComposeFile --project-directory $RepoRoot up -d vllm
if ($LASTEXITCODE -ne 0) {
    Stop-WithError -Step "3/8 docker compose up -d vllm" `
        -Reason "docker compose 回報失敗(exit code $LASTEXITCODE)" `
        -NextAction "執行 docker compose -f `"$ComposeFile`" --project-directory `"$RepoRoot`" logs vllm 查看細節"
}
Write-Ok "docker compose up -d vllm 已送出"

# ---------- 步驟 4/8:等待 vLLM healthy ----------
Write-Step "步驟 4/8:等待 vLLM 容器變為 healthy(逾時 420 秒;冷啟動需 170-260 秒屬正常)"
$vllmHealthyTimeoutSec = 420
$elapsed = 0
$vllmHealthy = $false
while ($elapsed -lt $vllmHealthyTimeoutSec) {
    $status = docker inspect --format '{{.State.Health.Status}}' qwen35_vllm 2>$null
    if ($status -eq 'healthy') { $vllmHealthy = $true; break }
    Start-Sleep -Seconds 10
    $elapsed += 10
    Write-Info "已等待 $elapsed 秒,目前狀態:$status"
}
if (-not $vllmHealthy) {
    Stop-WithError -Step "4/8 等待 vLLM healthy" `
        -Reason "等待 $vllmHealthyTimeoutSec 秒後容器仍非 healthy(最後狀態:$status)" `
        -NextAction "docker compose -f `"$ComposeFile`" logs vllm 查看啟動日誌,確認是否為顯存不足或下載權重過慢"
}
Write-Ok "vLLM 已 healthy(等待 $elapsed 秒)"

# ---------- 步驟 5/8:啟動 gateway ----------
Write-Step "步驟 5/8:啟動 Flask gateway(專案內 .venv,背景執行,監聽 $($GatewayHost):8080)"
$gatewayPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $gatewayPython)) {
    Stop-WithError -Step "5/8 啟動 gateway" `
        -Reason "找不到虛擬環境直譯器:$gatewayPython" `
        -NextAction "先建立虛擬環境:python -m venv .venv; .venv\Scripts\pip install -r gateway\requirements.txt"
}
$gatewayLogDir = Join-Path $RepoRoot 'logs\gateway'
New-Item -ItemType Directory -Force -Path $gatewayLogDir | Out-Null

$env:PYTHONPATH = Join-Path $RepoRoot 'gateway'
$env:LLM_BASE_URL = "http://localhost:$VllmPort/v1"
$env:LLM_MODEL_NAME = 'qwen3.5-0.8b'
$env:LLM_API_KEY = 'EMPTY'
$env:LOG_DIR = $gatewayLogDir
$env:LOG_LEVEL = 'INFO'
$env:GATEWAY_HOST = $GatewayHost
$env:GATEWAY_PORT = '8080'

$gatewayStdout = Join-Path $gatewayLogDir 'gateway.stdout.log'
$gatewayStderr = Join-Path $gatewayLogDir 'gateway.stderr.log'
$gatewayProcess = Start-Process -FilePath $gatewayPython -ArgumentList '-m', 'app.main' `
    -WorkingDirectory $RepoRoot -WindowStyle Hidden `
    -RedirectStandardOutput $gatewayStdout -RedirectStandardError $gatewayStderr -PassThru
Write-Ok "gateway 進程已啟動(PID $($gatewayProcess.Id)),日誌:$gatewayStdout / $gatewayStderr"

# ---------- 步驟 6/8:等待 gateway /healthz ----------
Write-Step "步驟 6/8:等待 gateway /healthz 回應"
$gatewayReadyTimeoutSec = 60
$elapsed = 0
$gatewayReady = $false
$healthzUrl = 'http://127.0.0.1:8080/healthz'
while ($elapsed -lt $gatewayReadyTimeoutSec) {
    $probe = Test-UrlHealthy -Url $healthzUrl
    if ($probe.Healthy) { $gatewayReady = $true; break }
    Start-Sleep -Seconds 3
    $elapsed += 3
    Write-Info "已等待 $elapsed 秒..."
}
if (-not $gatewayReady) {
    Stop-WithError -Step "6/8 等待 gateway /healthz" `
        -Reason "等待 $gatewayReadyTimeoutSec 秒後 $healthzUrl 仍未回應 200" `
        -NextAction "查看 $gatewayStderr 內容排查啟動錯誤(常見原因:8080 埠已被佔用、.venv 套件未裝齊)"
}
Write-Ok "gateway 已就緒(等待 $elapsed 秒)"

# ---------- 步驟 7/8:(可選)啟動 Open WebUI ----------
if ($WithOpenWebUI) {
    Write-Step "步驟 7/8:啟動 Open WebUI 容器(docker compose up -d open-webui)"
    # gateway 這裡是跑在宿主機(而非容器)的開發模式,open-webui 容器必須透過
    # host.docker.internal 連回宿主機的 gateway,不能用 compose 內網預設值
    $env:WEBUI_OPENAI_BASE_URL = "http://host.docker.internal:$($env:GATEWAY_PORT)/v1"
    Write-Info "Open WebUI 將連向宿主機 gateway:$($env:WEBUI_OPENAI_BASE_URL)"
    docker compose -f $ComposeFile --project-directory $RepoRoot up -d open-webui
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError -Step "7/8 docker compose up -d open-webui" `
            -Reason "docker compose 回報失敗(exit code $LASTEXITCODE)" `
            -NextAction "執行 docker compose -f `"$ComposeFile`" --project-directory `"$RepoRoot`" logs open-webui 查看細節"
    }
    Write-Ok "docker compose up -d open-webui 已送出"

    Write-Info "等待 Open WebUI 容器變為 healthy(逾時 120 秒;實測約 30-60 秒轉 healthy)..."
    $openWebUIHealthyTimeoutSec = 120
    $elapsed = 0
    $openWebUIHealthy = $false
    while ($elapsed -lt $openWebUIHealthyTimeoutSec) {
        $status = docker inspect --format '{{.State.Health.Status}}' qwen35_openwebui 2>$null
        if ($status -eq 'healthy') { $openWebUIHealthy = $true; break }
        Start-Sleep -Seconds 5
        $elapsed += 5
        Write-Info "已等待 $elapsed 秒,目前狀態:$status"
    }
    if (-not $openWebUIHealthy) {
        Stop-WithError -Step "7/8 等待 Open WebUI healthy" `
            -Reason "等待 $openWebUIHealthyTimeoutSec 秒後容器仍非 healthy(最後狀態:$status)" `
            -NextAction "docker compose -f `"$ComposeFile`" logs open-webui 查看啟動日誌"
    }
    Write-Ok "Open WebUI 已 healthy(等待 $elapsed 秒)"
} else {
    Write-Step "步驟 7/8:未指定 -WithOpenWebUI,略過 Open WebUI"
}

# ---------- 步驟 8/8:狀態總覽 ----------
Write-Step "步驟 8/8:服務狀態總覽"

$vllmProbe = Test-UrlHealthy -Url "http://localhost:$VllmPort/v1/models"
$gatewayProbe = Test-UrlHealthy -Url 'http://127.0.0.1:8080/healthz'

$summary = @()
$summary += [PSCustomObject]@{ 服務 = 'vLLM'; 網址 = "http://localhost:$VllmPort/v1/models"; 狀態 = $vllmProbe.Detail }
$summary += [PSCustomObject]@{ 服務 = 'Gateway'; 網址 = "http://$($GatewayHost):8080/healthz"; 狀態 = $gatewayProbe.Detail }
if ($WithOpenWebUI) {
    $openWebUIProbe = Test-UrlHealthy -Url 'http://localhost:3000/health'
    $summary += [PSCustomObject]@{ 服務 = 'Open WebUI'; 網址 = 'http://localhost:3000'; 狀態 = $openWebUIProbe.Detail }
}

$summary | Format-Table -AutoSize | Out-String | Write-Host

Write-Host "===== 啟動流程完成 =====" -ForegroundColor Cyan
