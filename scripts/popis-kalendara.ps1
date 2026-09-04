# Popisuje kalendare u Outlooku i broji stavke, radi provjere pretplate.
$ErrorActionPreference = 'Stop'
try { $outlook = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application') }
catch { $outlook = New-Object -ComObject Outlook.Application }
$ns = $outlook.GetNamespace('MAPI')

function Show-Calendars($folder, $depth) {
    foreach ($f in $folder.Folders) {
        if ($f.DefaultItemType -eq 1) {
            $n = try { $f.Items.Count } catch { '?' }
            $pad = ' ' * ($depth * 2)
            "{0}- {1,-42} stavki: {2}" -f $pad, $f.Name, $n | Write-Host
        }
        try { Show-Calendars $f ($depth + 1) } catch { }
    }
}

foreach ($store in $ns.Stores) {
    Write-Host "`n=== $($store.DisplayName) ==="
    try { Show-Calendars $store.GetRootFolder() 0 } catch { Write-Host "  (nedostupno)" }
}
