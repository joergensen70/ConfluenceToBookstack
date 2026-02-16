$ErrorActionPreference = 'Stop'

function Read-DotEnv([string]$path) {
    $map = @{}
    Get-Content -Path $path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { return }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim()
        $map[$k] = $v
    }
    return $map
}

$baseDir = "v:/Dokumente/Krankenversicherung/Patientenakte/Laborbefunde/ConfluenceToBookstack"
$envPath = Join-Path $baseDir '.env'
$outPath = Join-Path $baseDir '_bookstack_report.json'
$dotenv = Read-DotEnv $envPath

$baseUrl = ($dotenv['BOOKSTACK_BASE_URL']).TrimEnd('/')
$tokenId = $dotenv['BOOKSTACK_TOKEN_ID']
$tokenSecret = $dotenv['BOOKSTACK_TOKEN_SECRET']
$prefix = if ($dotenv.ContainsKey('BOOKSTACK_BOOK_PREFIX') -and $dotenv['BOOKSTACK_BOOK_PREFIX']) { $dotenv['BOOKSTACK_BOOK_PREFIX'] } else { 'Confluence -' }
$spaceKey = if ($dotenv.ContainsKey('CONFLUENCE_SPACE_KEY')) { $dotenv['CONFLUENCE_SPACE_KEY'] } else { 'CN' }

$headers = @{
    'Authorization' = "Token $tokenId`:$tokenSecret"
    'Content-Type'  = 'application/json'
}

function Get-AllItems([string]$path) {
    $items = @()
    $offset = 0
    $count = 100
    while ($true) {
        $url = "{0}{1}?count={2}&offset={3}" -f $baseUrl, $path, $count, $offset
        $resp = Invoke-RestMethod -Method Get -Uri $url -Headers $headers
        if ($resp.data) { $items += $resp.data }
        if (-not $resp.total -or ($offset + $count) -ge [int]$resp.total) { break }
        $offset += $count
    }
    return $items
}

function Get-CountSafe([string]$pathWithQuery) {
    try {
        $url = "{0}{1}" -f $baseUrl, $pathWithQuery
        $resp = Invoke-RestMethod -Method Get -Uri $url -Headers $headers
        if ($null -ne $resp.total) { return [int]$resp.total }
        if ($resp.data) { return @($resp.data).Count }
        return 0
    } catch {
        return -1
    }
}

$allBooks = Get-AllItems '/api/books'
$prefixedBooks = @($allBooks | Where-Object { $_.name -like "$prefix*" })

$bookSummaries = @()
foreach ($b in $prefixedBooks) {
    $chaptersCount = Get-CountSafe "/api/chapters?book_id=$($b.id)&count=1&offset=0"
    $pagesCount = Get-CountSafe "/api/pages?book_id=$($b.id)&count=1&offset=0"
    $bookSummaries += [PSCustomObject]@{
        id = $b.id
        name = $b.name
        slug = $b.slug
        chapters_count = $chaptersCount
        pages_count = $pagesCount
    }
}

$cnCandidates = @($bookSummaries | Where-Object { $_.name -match '(?i)\bCN\b|Confluence\s*-\s*CN|Computer\s*Netzwerk' })

$shelves = Get-AllItems '/api/shelves'
$shelf = $shelves | Where-Object { $_.name -eq 'Confluence Migration' } | Select-Object -First 1

if (-not $shelf) {
    $created = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/shelves" -Headers $headers -Body (@{ name = 'Confluence Migration' } | ConvertTo-Json)
    $shelfId = $created.id
} else {
    $shelfId = $shelf.id
}

$bookIds = @($prefixedBooks | ForEach-Object { [int]$_.id })
$updateBody = @{ name = 'Confluence Migration'; books = $bookIds } | ConvertTo-Json -Depth 5
$updatedShelf = Invoke-RestMethod -Method Put -Uri "$baseUrl/api/shelves/$shelfId" -Headers $headers -Body $updateBody

$shelfDetail = Invoke-RestMethod -Method Get -Uri "$baseUrl/api/shelves/$shelfId" -Headers $headers
$shelfBooks = @()
if ($shelfDetail.books) {
    foreach ($sb in $shelfDetail.books) {
        $shelfBooks += [PSCustomObject]@{ id = $sb.id; name = $sb.name; slug = $sb.slug }
    }
}

$report = [PSCustomObject]@{
    generated_at = (Get-Date).ToString('s')
    base_url = $baseUrl
    prefix = $prefix
    space_key = $spaceKey
    prefixed_books_total = @($bookSummaries).Count
    cn_candidates_total = @($cnCandidates).Count
    cn_candidates = $cnCandidates
    books = $bookSummaries
    shelf = [PSCustomObject]@{
        id = $shelfId
        name = 'Confluence Migration'
        books_total = @($shelfBooks).Count
        books = $shelfBooks
    }
}

$report | ConvertTo-Json -Depth 10 | Out-File -FilePath $outPath -Encoding utf8
Write-Output "REPORT_WRITTEN=$outPath"
