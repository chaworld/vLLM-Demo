<#
.SYNOPSIS
    冪等地偵測並修復本機 Docker Desktop(WSL2 後端)兩個「每次重啟後就消失」的已知故障。

.DESCRIPTION
    這台機器的 Docker Desktop 有兩個沒有官方根治方案的故障(docker/for-win#14390 仍 OPEN),
    每次 Docker Desktop 重啟(含開機)後都會重新出現,必須重新施加:

    1. /run/user/0 缺失
       症狀:docker run 失敗於
       "failed to create temp dir: stat /run/user/0/: no such file or directory"
       (docker pull / docker build 不受影響)。

    2. Windows bind mount 靜默失效
       症狀:-v "D:\proj:/data" 掛進容器後是空目錄,寫入不會回到宿主機,且完全不報錯。
       根因:Docker Desktop 把 D:\ 轉譯成 /run/desktop/mnt/host/d/,
       但該路徑在 dockerd 的 mount namespace 內只是空目錄,真正的 9p 掛載在 /mnt/d。

    本腳本每次執行都先「實際驗證」(而非猜測)這兩項是否正常,已正常就跳過,
    異常才施加修復,修復後再次驗證並回報結果。

.PARAMETER CheckOnly
    只偵測與回報,不施加任何修復。供驗收與日常健康檢查使用。
    此模式下腳本不會變更任何服務狀態;探針測試會建立暫存檔,但結束前一律刪除。

.EXAMPLE
    pwsh -File scripts\fix-docker-env.ps1
    偵測並在需要時施加修復。

.EXAMPLE
    pwsh -File scripts\fix-docker-env.ps1 -CheckOnly
    只檢查目前狀態,不做任何變更;exit code 0 = 兩項皆正常,非 0 = 至少一項異常。
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

function Write-Status {
    param(
        [Parameter(Mandatory)][string]$Message,
        [ValidateSet('OK', 'FIXED', 'FAIL', 'WARN', 'INFO')][string]$Level = 'INFO'
    )
    $displayText = switch ($Level) {
        'OK' { 'OK' }
        'FIXED' { '已修復' }
        'FAIL' { '失敗' }
        'WARN' { '警告' }
        default { '資訊' }
    }
    $color = switch ($Level) {
        'OK' { 'Green' }
        'FIXED' { 'Cyan' }
        'FAIL' { 'Red' }
        'WARN' { 'Yellow' }
        default { 'Gray' }
    }
    Write-Host ("[{0}] {1}" -f $displayText, $Message) -ForegroundColor $color
}

function Test-DockerDaemonRunning {
    docker info *>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-DockerRunOk {
    # 實際跑一個容器驗證 docker run 是否可用(驗證 /run/user/0 問題)。
    # 優先用已存在的 hello-world 映像;本機沒有的話改用 python:3.12-slim。
    docker image inspect hello-world *>$null
    if ($LASTEXITCODE -eq 0) {
        docker run --rm hello-world *>$null
    } else {
        docker run --rm python:3.12-slim sh -c "exit 0" *>$null
    }
    return ($LASTEXITCODE -eq 0)
}

function Test-BindMountOk {
    # 探針測試:把本目錄掛進容器,從容器內寫入一個帶隨機 token 的暫存檔,
    # 回宿主機比對內容是否一致。只用 ls 判斷不夠,因為失效時是「空目錄」而非「掛載失敗」。
    # 驗證完(不論成功或失敗)一律刪除暫存檔。
    $probeDir = $PSScriptRoot
    $token = [guid]::NewGuid().ToString('N')
    $probeFileName = ".bindmount_probe_$token.tmp"
    $hostProbePath = Join-Path $probeDir $probeFileName

    try {
        docker run --rm -v "${probeDir}:/probe" python:3.12-slim sh -c "echo $token > /probe/$probeFileName" *>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        if (-not (Test-Path -LiteralPath $hostProbePath)) {
            # 容器內寫入成功,但宿主機看不到檔案 → 典型的「空目錄」靜默失效
            return $false
        }
        $content = (Get-Content -LiteralPath $hostProbePath -Raw -ErrorAction SilentlyContinue)
        if ($null -ne $content) { $content = $content.Trim() }
        return ($content -eq $token)
    } finally {
        if (Test-Path -LiteralPath $hostProbePath) {
            Remove-Item -LiteralPath $hostProbePath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Repair-RunUser0 {
    Write-Status '施加修復:於 dockerd 的 mount namespace 內建立 /run/user/0 ...' 'WARN'
    wsl -d docker-desktop -e sh -c 'pid=$(pidof dockerd); nsenter -t $pid -m mkdir -p /run/user/0'
    return ($LASTEXITCODE -eq 0)
}

function Repair-BindMount {
    Write-Status '施加修復:重新綁定 /run/desktop/mnt/host/d 與 /run/desktop/mnt/host/c ...' 'WARN'
    wsl -d docker-desktop -e sh -c 'pid=$(pidof dockerd); nsenter -t $pid -m sh -c "mount --bind /mnt/d /run/desktop/mnt/host/d && mount --bind /mnt/c /run/desktop/mnt/host/c"'
    return ($LASTEXITCODE -eq 0)
}

# ================= 主流程 =================

Write-Host "===== Docker Desktop 環境修復檢查 =====" -ForegroundColor Cyan
if ($CheckOnly) {
    Write-Status '執行模式:-CheckOnly(只偵測,不施加任何修復)' 'INFO'
}

if (-not (Test-DockerDaemonRunning)) {
    Write-Status 'Docker Desktop 未啟動,請先啟動 Docker Desktop 後再執行本腳本(本腳本不會自行啟動它)。' 'FAIL'
    exit 1
}
Write-Status 'Docker Desktop 正在執行。' 'OK'

$allOk = $true

# ---- 檢查 1:/run/user/0(docker run 是否可用)----
Write-Status '檢查 1/2:docker run 是否可正常建立容器(/run/user/0)...' 'INFO'
$check1Ok = Test-DockerRunOk
if ($check1Ok) {
    Write-Status 'docker run 正常,已正常,略過修復。' 'OK'
} elseif ($CheckOnly) {
    Write-Status 'docker run 失敗(疑似 /run/user/0 缺失)。-CheckOnly 模式,不施加修復。' 'FAIL'
    $allOk = $false
} else {
    Write-Status 'docker run 失敗(疑似 /run/user/0 缺失),開始施加修復...' 'WARN'
    Repair-RunUser0 | Out-Null
    Start-Sleep -Seconds 1
    $check1Ok = Test-DockerRunOk
    if ($check1Ok) {
        Write-Status '修復後重新驗證 → docker run 已恢復正常。' 'FIXED'
    } else {
        Write-Status '修復後重新驗證仍失敗。' 'FAIL'
        $allOk = $false
    }
}

# ---- 檢查 2:Windows bind mount(探針測試)----
Write-Status '檢查 2/2:Windows bind mount 是否真的生效(探針測試)...' 'INFO'
if (-not $check1Ok) {
    Write-Status 'docker run 無法正常執行,略過 bind mount 探針(無法測試)。' 'FAIL'
    $allOk = $false
} else {
    $check2Ok = Test-BindMountOk
    if ($check2Ok) {
        Write-Status 'bind mount 正常,已正常,略過修復。' 'OK'
    } elseif ($CheckOnly) {
        Write-Status 'bind mount 失效(容器內寫入的檔案未回到宿主機)。-CheckOnly 模式,不施加修復。' 'FAIL'
        $allOk = $false
    } else {
        Write-Status 'bind mount 失效,開始施加修復...' 'WARN'
        Repair-BindMount | Out-Null
        Start-Sleep -Seconds 1
        $check2Ok = Test-BindMountOk
        if ($check2Ok) {
            Write-Status '修復後重新驗證 → bind mount 已恢復正常。' 'FIXED'
        } else {
            Write-Status '修復後重新驗證仍失敗。' 'FAIL'
            $allOk = $false
        }
    }
}

Write-Host "===== 檢查完成 =====" -ForegroundColor Cyan

if ($allOk) {
    Write-Status '兩項檢查皆正常。' 'OK'
    exit 0
} else {
    Write-Status '至少一項檢查失敗,詳見上方訊息。' 'FAIL'
    exit 1
}
