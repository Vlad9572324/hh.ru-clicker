$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Url = "http://127.0.0.1:8000"
$LogDir = Join-Path $Root "data"
$OutLog = Join-Path $LogDir "server.out.log"
$ErrLog = Join-Path $LogDir "server.err.log"

if (-not (Test-Path $Python)) {
  Write-Host "Virtual environment not found. Creating .venv..."
  python -m venv (Join-Path $Root ".venv")
  & $Python -m pip install -r (Join-Path $Root "requirements.txt")
}

New-Item -ItemType Directory -Force $LogDir | Out-Null

$existing = Get-CimInstance Win32_Process |
  Where-Object {
    ($_.CommandLine -like "*hh.ru-clicker*web_app.py*") -or
    ($_.ExecutablePath -like "$Root\.venv\Scripts\python.exe" -and $_.CommandLine -like "*web_app.py*")
  }

if (-not $existing) {
  Start-Process -FilePath $Python `
    -ArgumentList "web_app.py" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog | Out-Null
}

$ready = $false
for ($i = 0; $i -lt 30; $i += 1) {
  try {
    $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2
    if ($response.StatusCode -eq 200) {
      $ready = $true
      break
    }
  } catch {
    Start-Sleep -Seconds 1
  }
}

if ($ready) {
  Start-Process $Url
  Write-Host "HH Clicker is running at $Url"
} else {
  Write-Host "HH Clicker did not become ready. Check:"
  Write-Host $ErrLog
  exit 1
}
