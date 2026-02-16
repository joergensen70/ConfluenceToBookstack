$ErrorActionPreference = 'Stop'
$dir = "v:/Dokumente/Krankenversicherung/Patientenakte/Laborbefunde/ConfluenceToBookstack"
$out = Join-Path $dir "_log_status.txt"
$files = @(
    'cn_migration.log',
    'cn_migration.err.log',
    'migration_full_run.log',
    'migration_cn_run.out.log',
    'migration_cn_run.err.log',
    'migration_cn_followup.log'
)
if (Test-Path $out) { Remove-Item $out -Force }
foreach ($f in $files) {
    $p = Join-Path $dir $f
    Add-Content -Path $out -Value "=== $f ==="
    if (Test-Path $p) {
        Get-Content -Path $p -Tail 200 | Add-Content -Path $out
    } else {
        Add-Content -Path $out -Value 'MISSING'
    }
    Add-Content -Path $out -Value ''
}
