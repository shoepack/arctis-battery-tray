# Set up, build, and start Arctis Battery. Safe to re-run to update after
# pulling new code. Run with:
#   powershell -ExecutionPolicy Bypass -File install.ps1
Set-Location $PSScriptRoot

function Find-Python {
    # The py launcher first (python.org installs), then python on PATH. The
    # Microsoft Store's "python" placeholder fails the version check.
    foreach ($candidate in @(@("py", "-3"), @("python"))) {
        $exe, $rest = $candidate[0], @($candidate | Select-Object -Skip 1)
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $version = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) {
            $major, $minor = $version.Trim().Split(".") | ForEach-Object { [int]$_ }
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) { return ,$candidate }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/"
    Write-Host "(tick 'Add python.exe to PATH' during setup), then run this script again."
    exit 1
}

if (-not (Test-Path .venv\Scripts\python.exe)) {
    Write-Host "Creating a private Python environment in .venv ..."
    $exe, $rest = $python[0], @($python | Select-Object -Skip 1)
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Couldn't create the environment."; exit 1 }
}

Write-Host "Installing libraries ..."
.\.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Library install failed."; exit 1 }

# An already-running copy holds the files the build replaces.
Stop-Process -Name ArctisBattery -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

Write-Host "Building (takes about a minute) ..."
.\build.ps1
if ($LASTEXITCODE -ne 0) { exit 1 }

Start-Process -FilePath "dist\ArctisBattery\ArctisBattery.exe"
Write-Host ""
Write-Host "Done. Arctis Battery is running and will start with Windows."
Write-Host "Its icon may be hidden under the ^ arrow in the taskbar; drag it next to the clock to pin it."
Write-Host "Right-click the icon for options, or click it for details."
