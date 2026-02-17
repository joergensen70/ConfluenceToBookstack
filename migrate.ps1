# Confluence to BookStack Migration Tool v2 - Wrapper mit Retry-Logik
# Behebt Windows-spezifische Module-Import-Probleme beim ersten Start

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $scriptDir ".venv\Scripts\python.exe"
$scriptPath = Join-Path $scriptDir "confluence_to_bookstack_migration_v2.py"

if (-not (Test-Path $pythonPath)) {
    Write-Host "Fehler: Python venv nicht gefunden!" -ForegroundColor Red
    Write-Host "Erwarteter Pfad: $pythonPath" -ForegroundColor Yellow
    Write-Host "" 
    Write-Host "Lösung:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Cyan
    Write-Host "  & .\.venv\Scripts\pip.exe install requests" -ForegroundColor Cyan
    exit 1
}

if (-not (Test-Path $scriptPath)) {
    Write-Host "Fehler: Migration-Skript nicht gefunden!" -ForegroundColor Red
    Write-Host "Erwarteter Pfad: $scriptPath" -ForegroundColor Yellow
    exit 1
}

# Versuche das Skript auszuführen (mit Retry bei Windows-Import-Problemen)
$maxAttempts = 2
$attempt = 1

while ($attempt -le $maxAttempts) {
    if ($attempt -gt 1) {
        Write-Host "Windows File-Lock erkannt, wiederhole Versuch ($attempt/$maxAttempts)..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
    
    # Führe das Skript aus
    & $pythonPath $scriptPath @Arguments
    $exitCode = $LASTEXITCODE
    
    # Wenn erfolgreich oder nicht der spezifische Import-Fehler, beende
    if ($exitCode -eq 0 -or $attempt -eq $maxAttempts) {
        exit $exitCode
    }
    
    $attempt++
}

exit 1
