# Build dist\ArctisBattery\ArctisBattery.exe (one-folder build: starts
# instantly at login, unlike --onefile which unpacks itself every launch).
# Exit codes are checked by hand: PyInstaller logs to stderr, which Windows
# PowerShell would otherwise treat as a failure.
Set-Location $PSScriptRoot
.\.venv\Scripts\python.exe -m pytest -q tests
if ($LASTEXITCODE -ne 0) { Write-Host "Tests failed; not building."; exit 1 }
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed `
    --name ArctisBattery `
    --exclude-module tkinter --exclude-module ssl --exclude-module _ssl `
    --exclude-module PySide6.QtNetwork `
    run.pyw 2>&1 | Out-File -Encoding utf8 build.log
if ($LASTEXITCODE -ne 0) { Write-Host "PyInstaller failed; see build.log"; exit 1 }
# Not used by a widgets-only tray app: software OpenGL fallback and Qt's
# own UI translations.
$qt = "dist\ArctisBattery\_internal\PySide6"
Remove-Item "$qt\opengl32sw.dll", "$qt\translations" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Built: $PSScriptRoot\dist\ArctisBattery\ArctisBattery.exe"
