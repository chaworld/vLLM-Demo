<#
REST API 呼叫範例(Windows PowerShell 7+)。
用法:pwsh -File rest_api_examples.ps1 [-GatewayUrl <url>] [-VllmUrl <url>]
#>
param(
    [string]$GatewayUrl = 'http://localhost:8080',
    [string]$VllmUrl    = 'http://localhost:8000',
    [string]$Model      = 'qwen3.5-0.8b'
)

$ErrorActionPreference = 'Stop'

function Write-Section([string]$Title) {
    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
}

function Invoke-Json([string]$Uri, [hashtable]$Body) {
    $json = $Body | ConvertTo-Json -Depth 10
    # PowerShell 預設以 UTF-16 送出字串,明確指定 UTF-8 才能正確傳遞中文
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    Invoke-RestMethod -Uri $Uri -Method Post -ContentType 'application/json; charset=utf-8' -Body $bytes
}

Write-Section '1. gateway 存活檢查'
Invoke-RestMethod -Uri "$GatewayUrl/healthz" | ConvertTo-Json -Depth 5

Write-Section '2. gateway 就緒檢查(會實際打上游 vLLM)'
Invoke-RestMethod -Uri "$GatewayUrl/readyz" | ConvertTo-Json -Depth 5

Write-Section '3. 可用模型清單'
Invoke-RestMethod -Uri "$GatewayUrl/v1/models" | ConvertTo-Json -Depth 5

Write-Section '4. 對話補全(gateway 已強制關閉 thinking)'
$chat = Invoke-Json "$GatewayUrl/v1/chat/completions" @{
    model       = $Model
    messages    = @(
        @{ role = 'system'; content = '你是一個以繁體中文回答的助理。' },
        @{ role = 'user';   content = '用一句話說明什麼是向量資料庫。' }
    )
    temperature = 0.3
    max_tokens  = 256
}
Write-Host $chat.choices[0].message.content

Write-Section '5. 服務指標'
Invoke-RestMethod -Uri "$GatewayUrl/metrics" | ConvertTo-Json -Depth 5

Write-Section '6. 直連 vLLM(繞過 gateway 時,必須自行帶 chat_template_kwargs 才能關閉 thinking)'
$direct = Invoke-Json "$VllmUrl/v1/chat/completions" @{
    model                = $Model
    messages             = @(@{ role = 'user'; content = '1 加 1 等於多少?只回答數字。' })
    max_tokens           = 32
    chat_template_kwargs = @{ enable_thinking = $false }
}
Write-Host $direct.choices[0].message.content
