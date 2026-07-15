$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

function Start-StreamlitApp {
    param(
        [int]$Port,
        [string]$Script
    )

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        return
    }

    Start-Process `
        -FilePath $Python `
        -ArgumentList @("-m", "streamlit", "run", $Script, "--server.port", "$Port") `
        -WorkingDirectory $ProjectDir `
        -WindowStyle Hidden | Out-Null
}

Start-StreamlitApp -Port 8501 -Script "main.py"
Start-Sleep -Seconds 4

$hostName = $env:COMPUTERNAME
$addresses = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254*" } |
    Select-Object -ExpandProperty IPAddress

Write-Host "중앙서버: http://$hostName`:8501"
Write-Host "관리자 화면: http://$hostName`:8501?view=manager"
foreach ($address in $addresses) {
    Write-Host "중앙서버(IP): http://$address`:8501"
    Write-Host "관리자 화면(IP): http://$address`:8501?view=manager"
}
