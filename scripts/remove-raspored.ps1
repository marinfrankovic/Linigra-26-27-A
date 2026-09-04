# Brise unose rasporeda iz zadanog Outlook kalendara.
# Popis predmeta i raspon datuma cita iz objavljenog .ics-a, pa se ne pogadja rucno.
#   powershell -File remove-raspored.ps1                 -> samo pregled
#   powershell -File remove-raspored.ps1 -Delete         -> brisanje
#   powershell -File remove-raspored.ps1 -Folder 'Raspored' -Delete
param(
    [string]$Folder = 'Calendar',
    [string]$Account = 'marin@frankovic.net',
    [string]$IcsUrl = 'https://marinfrankovic.github.io/Linigra-26-27-A/linigra-1a.ics',
    [switch]$Delete
)

$ErrorActionPreference = 'Stop'

# --- referentni popis iz objavljenog kalendara -------------------------------
$ics = (Invoke-WebRequest $IcsUrl -UseBasicParsing).RawContentStream
$reader = New-Object System.IO.StreamReader($ics, [System.Text.Encoding]::UTF8)
$text = $reader.ReadToEnd()
$text = $text -replace "`r`n ", ''    # odmotaj prelomljene retke

$subjects = [System.Collections.Generic.HashSet[string]]::new()
foreach ($m in [regex]::Matches($text, '(?m)^SUMMARY:(.+)$')) {
    $s = $m.Groups[1].Value -replace '\\,', ',' -replace '\\;', ';' -replace '\\\\', '\'
    [void]$subjects.Add($s.Trim())
}

# Samo DTSTART unutar VEVENT-a; VTIMEZONE ima laznji DTSTART iz 1970.
$eventsOnly = $text.Substring($text.IndexOf('BEGIN:VEVENT'))
$dates = [regex]::Matches($eventsOnly, 'DTSTART[^:]*:(\d{8})') | ForEach-Object {
    [datetime]::ParseExact($_.Groups[1].Value, 'yyyyMMdd', $null)
}
$from = ($dates | Measure-Object -Minimum).Minimum
$to = ($dates | Measure-Object -Maximum).Maximum.AddDays(21)

Write-Host "Referenca iz .ics-a: $($subjects.Count) razlicitih naslova, raspon $($from.ToString('yyyy-MM-dd')) - $($to.ToString('yyyy-MM-dd'))"

# --- Outlook -----------------------------------------------------------------
try { $outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
catch { $outlook = New-Object -ComObject Outlook.Application }
$ns = $outlook.GetNamespace('MAPI')

$store = $ns.Stores | Where-Object { $_.DisplayName -eq $Account }
if (-not $store) { throw "Racun '$Account' nije pronaden. Dostupni: $(($ns.Stores | ForEach-Object DisplayName) -join ', ')" }

$root = $store.GetRootFolder()
$cal = $null
foreach ($f in $root.Folders) {
    if ($f.Name -eq $Folder -and $f.DefaultItemType -eq 1) { $cal = $f; break }
    foreach ($sub in $f.Folders) {
        if ($sub.Name -eq $Folder -and $sub.DefaultItemType -eq 1) { $cal = $sub; break }
    }
    if ($cal) { break }
}
if (-not $cal) { throw "Kalendar '$Folder' nije pronaden u racunu '$Account'." }

Write-Host "Kalendar: '$($cal.Name)' u '$($cal.Store.DisplayName)' (ukupno stavki: $($cal.Items.Count))`n"

$hits = @()
foreach ($item in $cal.Items) {
    if ($item.Class -ne 26) { continue }
    $subject = ([string]$item.Subject).Trim()
    $inRange = $item.Start -ge $from -and $item.Start -le $to
    $legacy = ([string]$item.Location) -match 'LINIGRA' -or ([string]$item.Body) -match 'Razred 1\.A'
    if ($legacy -or ($inRange -and $subjects.Contains($subject))) {
        $hits += [pscustomobject]@{ Subject = $subject; Start = $item.Start; Item = $item }
    }
}

Write-Host "Pronadenih stavki rasporeda: $($hits.Count)"
if ($hits.Count -eq 0) { return }

$hits | Group-Object Subject | Sort-Object Count -Descending |
    Select-Object Count, Name | Format-Table -AutoSize | Out-String | Write-Host
Write-Host ("Raspon: {0} - {1}" -f ($hits | Measure-Object Start -Minimum).Minimum.ToString('yyyy-MM-dd'),
                                   ($hits | Measure-Object Start -Maximum).Maximum.ToString('yyyy-MM-dd'))

if (-not $Delete) { Write-Host "`nSamo pregled. Nista nije obrisano."; return }

$n = 0
foreach ($h in $hits) { $h.Item.Delete(); $n++ }
Write-Host "`nObrisano: $n (u mapi Deleted Items)."
