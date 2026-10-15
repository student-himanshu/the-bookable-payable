# setup.ps1 - non-destructive environment setup (Windows PowerShell 5.1+ / PowerShell 7)
# Usage:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# 1. Python >= 3.10
$py = $null
foreach ($cand in @("py -3", "python", "python3")) {
    try {
        $v = & cmd /c "$cand --version 2>&1"
        if ($v -match "Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -gt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 10)) { $py = $cand; break }
        }
    } catch { }
}
if (-not $py) { Write-Error "Python 3.10+ not found on PATH."; exit 1 }
Write-Host "Using interpreter: $py"

# 2. Create the venv only if it does not exist (never deletes anything)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & cmd /c "$py -m venv .venv"
    if ($LASTEXITCODE -ne 0) { Write-Error "venv creation failed."; exit 1 }
} else { Write-Host ".venv already exists - reusing." }

# 3. Install dependencies
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Error "pip upgrade failed."; exit 1 }
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "Dependency installation failed."; exit 1 }

# 4. Report external tools (warn only; needed from Phase 2 for OCR / the inventory tool)
foreach ($tool in @("pdftotext", "pdftoppm", "tesseract")) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) { Write-Host "found:   $tool" }
    else { Write-Warning "missing: $tool (needed for OCR/inventory; see README)" }
}

# 5. Baseline tests
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { Write-Error "Baseline tests failed."; exit 1 }
Write-Host "Setup complete."
exit 0
