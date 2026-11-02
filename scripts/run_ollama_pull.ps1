$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$log = "$root\logs\ollama_pull_bge-m3.log"
for ($i = 1; $i -le 3; $i++) {
    "=== attempt $i ===" | Out-File -FilePath $log -Append -Encoding utf8
    ollama pull bge-m3 *>&1 | Out-File -FilePath $log -Append -Encoding utf8
    if ($LASTEXITCODE -eq 0) {
        "PULL_EXIT=0 (success on attempt $i)" | Out-File -FilePath $log -Append -Encoding utf8
        exit 0
    }
    Start-Sleep -Seconds 5
}
"PULL_EXIT=1 (all attempts failed)" | Out-File -FilePath $log -Append -Encoding utf8