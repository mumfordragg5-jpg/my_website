# 公众号写作工作台 —— 启动脚本
# 用法：双击 run.bat，或在本目录 PowerShell 里执行 .\run.ps1

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8765
$url  = "http://127.0.0.1:$port/"

# ---- 1) 先看端口有没有被占（已有实例就直接打开浏览器） ----
function Test-Port($p) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ok = $c.ConnectAsync("127.0.0.1", $p).Wait(800)
        $c.Close()
        return $ok
    } catch { return $false }
}

if (Test-Port $port) {
    Write-Host "工作台已经在运行了：$url" -ForegroundColor Green
    Write-Host "已帮你打开浏览器（这个窗口可以关掉）。" -ForegroundColor Gray
    Start-Process $url
    Start-Sleep -Seconds 2
    exit
}

# ---- 2) 挑解释器（优先带 jieba 的隔离 venv） ----
$venvPy = "C:\Users\wang\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
$sysPy  = "C:\Users\wang\.workbuddy\binaries\python\versions\3.13.12\python.exe"

if (Test-Path $venvPy) {
    $py = $venvPy
    Write-Host "使用环境：隔离 venv（含 jieba 分词）" -ForegroundColor Green
} elseif (Test-Path $sysPy) {
    $py = $sysPy
    Write-Host "使用环境：系统 Python（无 jieba，关键词质量下降）" -ForegroundColor Yellow
} else {
    $py = "python"
    Write-Host "使用环境：PATH 中的 python" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "启动中，稍后会自动打开浏览器：$url" -ForegroundColor Cyan
Write-Host "（这个窗口不要关，关掉就等于关掉工作台）" -ForegroundColor Gray
Write-Host ""

# ---- 3) 后台等 3 秒再开浏览器，前台跑服务（窗口关=服务停） ----
Start-Job -ScriptBlock {
    param($u)
    Start-Sleep -Seconds 3
    Start-Process $u
} -ArgumentList $url | Out-Null

& $py "$here\app.py" --port $port
$rc = $LASTEXITCODE

Write-Host ""
if ($rc -ne 0) {
    Write-Host "服务异常退出（代码 $rc），把上面这条报错发我就行。" -ForegroundColor Red
} else {
    Write-Host "服务已退出。" -ForegroundColor Yellow
}
Read-Host "按回车关闭窗口"
