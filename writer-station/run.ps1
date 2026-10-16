# 公众号写作工作台 —— 启动脚本
# 用法：在 PowerShell 里执行  .\run.ps1
#      或双击 run.bat

$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
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
& $py "$here\app.py" --port 8765
