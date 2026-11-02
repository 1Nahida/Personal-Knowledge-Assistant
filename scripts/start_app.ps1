# 启动 PKA 前端（Streamlit）
# 用法：右键"使用 PowerShell 运行"，或在终端执行 .\scripts\start_app.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "未找到虚拟环境: $py" -ForegroundColor Red
    Write-Host "请先执行: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

# 依赖自检：缺包直接提示，避免启动后才报错
& $py -c "import streamlit, chromadb, langchain_ollama" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "依赖不完整，正在安装..." -ForegroundColor Yellow
    & $py -m pip install -r (Join-Path $root "requirements.txt")
}

# Ollama 可用性提示（不阻塞启动）
try {
    $r = Invoke-WebRequest -Uri "http://localhost:11434/api/version" -TimeoutSec 3 -UseBasicParsing
    Write-Host "Ollama 在线: $($r.Content)" -ForegroundColor Green
} catch {
    Write-Host "Ollama 未响应，本地模型将不可用（云端源仍可切换）。启动命令: ollama serve" -ForegroundColor Yellow
}

Write-Host "启动前端 http://localhost:8501 ..." -ForegroundColor Cyan
& $py -m streamlit run (Join-Path $root "app.py") --server.headless=false --browser.gatherUsageStats=false