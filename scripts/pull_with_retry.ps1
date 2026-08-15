<#
在網路不穩的環境下重試拉取大型映像。
docker pull 會保留已完成的層,因此每次重試都會累積進度。
用法:pwsh -File scripts/pull_with_retry.ps1 -Image vllm/vllm-openai:latest -MaxAttempts 6
#>
param(
    [string]$Image = 'vllm/vllm-openai:latest',
    [int]$MaxAttempts = 6,
    [int]$DelaySeconds = 10
)

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Write-Host "===== 第 $attempt/$MaxAttempts 次嘗試 $(Get-Date -Format 'HH:mm:ss') ====="
    docker pull $Image 2>&1 | Select-Object -Last 3

    if (docker image inspect $Image 2>$null) {
        Write-Host "===== 成功:$Image 已完整下載 ====="
        exit 0
    }

    Write-Host "===== 第 $attempt 次失敗,${DelaySeconds}s 後重試 ====="
    Start-Sleep -Seconds $DelaySeconds
}

Write-Host "===== 放棄:$MaxAttempts 次嘗試皆失敗 ====="
exit 1
