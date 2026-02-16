Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

function Load-EnvFile {
    param([string]$Path)
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { return }
        $parts = $line.Split('=', 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key) {
            [Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
}

function Normalize-Title {
    param([string]$Title)
    if (-not $Title) { return '' }
    $t = $Title.ToLowerInvariant().Trim()
    $t = [regex]::Replace($t, '\s+', ' ')
    return $t
}

function Normalize-HtmlToText {
    param([string]$Html)
    if (-not $Html) { return '' }

    $text = $Html
    $text = [regex]::Replace($text, '(?is)<script.*?</script>', ' ')
    $text = [regex]::Replace($text, '(?is)<style.*?</style>', ' ')
    $text = [regex]::Replace($text, '(?is)<[^>]+>', ' ')
    $text = [System.Net.WebUtility]::HtmlDecode($text)
    $text = $text.ToLowerInvariant()
    $text = [regex]::Replace($text, '\s+', ' ').Trim()
    return $text
}

function Get-BookStackPaged {
    param(
        [string]$BaseUrl,
        [hashtable]$Headers,
        [string]$Path,
        [int]$Count = 500
    )

    $items = @()
    $offset = 0
    while ($true) {
        $sep = if ($Path.Contains('?')) { '&' } else { '?' }
        $url = "$BaseUrl$Path${sep}count=$Count&offset=$offset"
        $resp = Invoke-RestMethod -Method Get -Uri $url -Headers $Headers -TimeoutSec 120
        $batch = @($resp.data)
        if ($batch.Count -eq 0) { break }

        $items += $batch

        $total = 0
        if ($resp.PSObject.Properties.Name -contains 'total') {
            $total = [int]$resp.total
        } else {
            $total = $items.Count
        }

        $offset += $batch.Count
        if ($offset -ge $total) { break }
    }
    return $items
}

function Get-ConfluenceSpaces {
    param(
        [string]$BaseUrl,
        [hashtable]$Headers
    )

    $spaces = @()
    $start = 0
    $limit = 200

    while ($true) {
        $url = "$BaseUrl/wiki/rest/api/space?limit=$limit&start=$start"
        $resp = Invoke-RestMethod -Method Get -Uri $url -Headers $Headers -TimeoutSec 120
        $batch = @($resp.results)
        if ($batch.Count -eq 0) { break }

        $spaces += $batch
        $size = if ($resp.PSObject.Properties.Name -contains 'size') { [int]$resp.size } else { $batch.Count }
        if ($size -lt $limit) { break }
        $start += $size
    }

    return $spaces
}

function Get-ConfluencePageCount {
    param(
        [string]$BaseUrl,
        [hashtable]$Headers,
        [string]$SpaceKey
    )

    $start = 0
    $limit = 50
    $count = 0
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'

    while ($true) {
        $cql = [uri]::EscapeDataString("space=`"$SpaceKey`" and type=page")
        $url = "$BaseUrl/wiki/rest/api/content/search?cql=$cql&limit=$limit&start=$start"
        $resp = Invoke-RestMethod -Method Get -Uri $url -Headers $Headers -TimeoutSec 120

        $batch = @($resp.results)
        if ($batch.Count -eq 0) { break }

        $newItems = 0
        foreach ($item in $batch) {
            $id = [string]$item.id
            if ($seen.Add($id)) {
                $newItems += 1
            }
        }
        $count += $newItems

        if ($newItems -eq 0) { break }

        $size = if ($resp.PSObject.Properties.Name -contains 'size') { [int]$resp.size } else { $batch.Count }
        if ($size -lt $limit) { break }
        $start += $size
    }

    return $count
}

Load-EnvFile -Path '.env'

$confBase = $env:CONFLUENCE_BASE_URL.TrimEnd('/')
$confPair = "{0}:{1}" -f $env:CONFLUENCE_EMAIL, $env:CONFLUENCE_API_TOKEN
$confB64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($confPair))
$confHeaders = @{ Authorization = "Basic $confB64"; Accept = 'application/json' }

$bookBase = $env:BOOKSTACK_BASE_URL.TrimEnd('/')
$bookHeaders = @{ Authorization = "Token $($env:BOOKSTACK_TOKEN_ID):$($env:BOOKSTACK_TOKEN_SECRET)"; Accept = 'application/json' }

$books = Get-BookStackPaged -BaseUrl $bookBase -Headers $bookHeaders -Path '/api/books'
$allPages = Get-BookStackPaged -BaseUrl $bookBase -Headers $bookHeaders -Path '/api/pages'

$migratedBooks = @($books | Where-Object { $_.name -match '^Confluence\s*-' })
$migratedBookIds = @($migratedBooks | ForEach-Object { [int]$_.id })
$migratedPages = @($allPages | Where-Object { [int]$_.book_id -in $migratedBookIds })
$nonMigratedPages = @($allPages | Where-Object { [int]$_.book_id -notin $migratedBookIds })

# 1) Confluence vs BookStack count check
$spaces = Get-ConfluenceSpaces -BaseUrl $confBase -Headers $confHeaders
$countResults = @()

foreach ($book in $migratedBooks) {
    $bookName = [string]$book.name
    $spaceNameGuess = ($bookName -replace '^Confluence\s*-\s*', '').Trim()
    $matchingSpace = $spaces | Where-Object { $_.name -eq $spaceNameGuess } | Select-Object -First 1

    $spaceKey = $null
    $confCount = $null
    if ($matchingSpace) {
        $spaceKey = [string]$matchingSpace.key
        $confCount = Get-ConfluencePageCount -BaseUrl $confBase -Headers $confHeaders -SpaceKey $spaceKey
    }

    $bsCount = @($migratedPages | Where-Object { [int]$_.book_id -eq [int]$book.id }).Count

    $countResults += [PSCustomObject]@{
        book_id            = [int]$book.id
        book_name          = $bookName
        inferred_space_key = $spaceKey
        confluence_pages   = $confCount
        bookstack_pages    = $bsCount
        match              = ($confCount -ne $null -and [int]$confCount -eq [int]$bsCount)
    }
}

# 2) Duplicate detection (migrated pages duplicated in non-migrated area)
$nonMigByTitle = @{}
foreach ($p in $nonMigratedPages) {
    $key = Normalize-Title -Title ([string]$p.name)
    if (-not $nonMigByTitle.ContainsKey($key)) {
        $nonMigByTitle[$key] = New-Object System.Collections.ArrayList
    }
    [void]$nonMigByTitle[$key].Add($p)
}

$pageDetailCache = @{}
function Get-PageNormalizedText {
    param(
        [int]$PageId,
        [string]$BaseUrl,
        [hashtable]$Headers,
        [hashtable]$Cache
    )
    $cacheKey = [string]$PageId
    if ($Cache.ContainsKey($cacheKey)) {
        return [string]$Cache[$cacheKey]
    }

    $detail = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/pages/$PageId" -Headers $Headers -TimeoutSec 120
    $html = ''
    if ($detail.PSObject.Properties.Name -contains 'raw_html' -and $detail.raw_html) {
        $html = [string]$detail.raw_html
    } elseif ($detail.PSObject.Properties.Name -contains 'html' -and $detail.html) {
        $html = [string]$detail.html
    }

    $normalized = Normalize-HtmlToText -Html $html
    $Cache[$cacheKey] = $normalized
    return $normalized
}

$duplicatesToDelete = New-Object System.Collections.ArrayList

foreach ($mig in $migratedPages) {
    $titleKey = Normalize-Title -Title ([string]$mig.name)
    if (-not $nonMigByTitle.ContainsKey($titleKey)) { continue }

    $migText = Get-PageNormalizedText -PageId ([int]$mig.id) -BaseUrl $bookBase -Headers $bookHeaders -Cache $pageDetailCache
    if ([string]::IsNullOrWhiteSpace($migText) -or $migText.Length -lt 40) { continue }

    foreach ($other in $nonMigByTitle[$titleKey]) {
        $otherText = Get-PageNormalizedText -PageId ([int]$other.id) -BaseUrl $bookBase -Headers $bookHeaders -Cache $pageDetailCache
        if ($migText -eq $otherText) {
            [void]$duplicatesToDelete.Add([PSCustomObject]@{
                migrated_page_id   = [int]$mig.id
                migrated_page_name = [string]$mig.name
                migrated_book_id   = [int]$mig.book_id
                other_page_id      = [int]$other.id
                other_page_name    = [string]$other.name
                other_book_id      = [int]$other.book_id
            })
            break
        }
    }
}

# 3) Delete matched migrated duplicates
$deletions = New-Object System.Collections.ArrayList
foreach ($dup in $duplicatesToDelete) {
    try {
        Invoke-RestMethod -Method Delete -Uri "$bookBase/api/pages/$($dup.migrated_page_id)" -Headers $bookHeaders -TimeoutSec 120 | Out-Null
        [void]$deletions.Add([PSCustomObject]@{
            page_id = $dup.migrated_page_id
            page_name = $dup.migrated_page_name
            status = 'deleted'
            duplicate_of = $dup.other_page_id
        })
    } catch {
        [void]$deletions.Add([PSCustomObject]@{
            page_id = $dup.migrated_page_id
            page_name = $dup.migrated_page_name
            status = 'failed'
            duplicate_of = $dup.other_page_id
            error = $_.Exception.Message
        })
    }
}

# 4) Write report
$report = [PSCustomObject]@{
    generated_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    migrated_books = @($migratedBooks | Select-Object id, name)
    counts = $countResults
    duplicate_candidates = $duplicatesToDelete
    deletions = $deletions
}

$reportJson = $report | ConvertTo-Json -Depth 8
$reportPath = Join-Path $PSScriptRoot 'migration_verification_report.json'
[System.IO.File]::WriteAllText($reportPath, $reportJson, [System.Text.Encoding]::UTF8)

Write-Output "REPORT_PATH=$reportPath"
Write-Output "MIGRATED_BOOKS=$($migratedBooks.Count)"
foreach ($c in $countResults) {
    Write-Output ("COUNT book={0} space={1} confluence={2} bookstack={3} match={4}" -f $c.book_name, $c.inferred_space_key, $c.confluence_pages, $c.bookstack_pages, $c.match)
}
Write-Output "DUPLICATE_CANDIDATES=$($duplicatesToDelete.Count)"
Write-Output "DELETED=$(@($deletions | Where-Object { $_.status -eq 'deleted' }).Count)"
Write-Output "FAILED_DELETIONS=$(@($deletions | Where-Object { $_.status -eq 'failed' }).Count)"
