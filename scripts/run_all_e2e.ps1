# 依次跑三条端到端（隔离数据目录，不污染真实知识库）
# 用法：.\scripts\run_all_e2e.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONIOENCODING = "utf-8"
$env:PKA_DATA_DIR = Join-Path $root "logs\_e2e_data"
$env:PKA_LOG_DIR  = Join-Path $root "logs\_e2e_logs"
Remove-Item $env:PKA_DATA_DIR, $env:PKA_LOG_DIR -Recurse -Force -ErrorAction SilentlyContinue

$py = Join-Path $root ".venv\Scripts\python.exe"
$failed = @()
foreach ($n in 1, 2, 3) {
    Write-Host "`n======== e2e_phase$n ========" -ForegroundColor Cyan
    & $py "scripts\e2e_phase$n.py" 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch "telemetry"
    if ($LASTEXITCODE -ne 0) { $failed += "e2e_phase$n" }
}

if ($failed.Count -gt 0) {
    Write-Host "`nFAILED: $($failed -join ", ")" -ForegroundColor Red
    exit 1
}
Write-Host "`nALL E2E PASS" -ForegroundColor Green
exit 0