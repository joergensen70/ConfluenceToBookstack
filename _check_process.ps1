$ErrorActionPreference = 'Stop'
$out = "v:/Dokumente/Krankenversicherung/Patientenakte/Laborbefunde/ConfluenceToBookstack/_process_status.txt"
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match 'python' -and $_.CommandLine -match 'confluence_to_bookstack_migration.py'
}
if ($procs) {
    $procs | Select-Object ProcessId, Name, CommandLine | Format-List | Out-File -FilePath $out -Encoding utf8
} else {
    "NO_MATCHING_PROCESS" | Out-File -FilePath $out -Encoding utf8
}
