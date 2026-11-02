$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& "$root\.venv\Scripts\python.exe" -m pip install -r "$root\requirements.txt" *>&1 | Out-File -FilePath "$root\logs\pip_install.log" -Encoding utf8
"PIP_EXIT=$LASTEXITCODE" | Out-File -FilePath "$root\logs\pip_install.log" -Append -Encoding utf8
