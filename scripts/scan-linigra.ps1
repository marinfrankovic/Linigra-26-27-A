# Pronalazi (i po potrebi brise) LINIGRA unose u Outlook kalendaru "Calendar".
# Pokretanje:  powershell -File scan-linigra.ps1            -> samo popis
#              powershell -File scan-linigra.ps1 -Delete    -> brisanje
param([switch]$Delete)

$ErrorActionPreference = 'Stop'

try {
    $outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
    Write-Host "Spojen na pokrenuti Outlook."
} catch {
    $outlook = New-Object -ComObject Outlook.Application
    Write-Host "Pokrenut novi Outlook COM objekt."
}

$ns = $outlook.GetNamespace('MAPI')
$cal = $ns.GetDefaultFolder(9)   # olFolderCalendar
Write-Host "Kalendar: '$($cal.Name)' u trezoru '$($cal.Store.DisplayName)'"

$items = $cal.Items
$items.IncludeRecurrences = $false
Write-Host "Ukupno stavki u kalendaru: $($items.Count)`n"

$hits = @()
foreach ($item in $items) {
    if ($item.Class -ne 26) { continue }   # olAppointment
    $subject = [string]$item.Subject
    $location = [string]$item.Location
    $body = [string]$item.Body
    if ($location -match 'LINIGRA' -or $subject -match 'LINIGRA' -or $body -match 'Razred 1\.A') {
        $hits += [pscustomobject]@{
            Subject = $subject
            Start   = $item.Start
            AllDay  = $item.AllDayEvent
            Item    = $item
        }
    }
}

Write-Host "Pronadenih LINIGRA stavki: $($hits.Count)"
if ($hits.Count -eq 0) { return }

$hits | Group-Object Subject | Sort-Object Count -Descending |
    Select-Object Count, Name | Format-Table -AutoSize | Out-String | Write-Host

$min = ($hits | Measure-Object -Property Start -Minimum).Minimum
$max = ($hits | Measure-Object -Property Start -Maximum).Maximum
Write-Host "Raspon datuma: $($min.ToString('yyyy-MM-dd')) -> $($max.ToString('yyyy-MM-dd'))"

if (-not $Delete) {
    Write-Host "`nOvo je samo pregled. Nista nije obrisano."
    return
}

$deleted = 0
foreach ($h in $hits) {
    $h.Item.Delete()
    $deleted++
}
Write-Host "`nObrisano stavki: $deleted (nalaze se u mapi Deleted Items)."
