# Simple setup script for Windows PowerShell
# Creates a venv and installs dependencies

$ErrorActionPreference = "Stop"

if (-not (Test-Path .\.venv)) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r .\requirements.txt

Write-Host "Setup complete. Activate with: .\.venv\Scripts\Activate.ps1"
