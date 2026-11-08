# Familiehub – legger inn de automatiske kjøringene i Oppgaveplanlegging (fase 6).
# Kjør fra familiehub-mappen:   powershell -ExecutionPolicy Bypass -File sett-opp-oppgaver.ps1
# Fjern alle igjen:             powershell -ExecutionPolicy Bypass -File sett-opp-oppgaver.ps1 -Fjern
# Kan kjøres flere ganger – eksisterende oppgaver erstattes. Krever ikke administrator.

param([switch]$Fjern)

$mappe  = $PSScriptRoot
$python = Join-Path $mappe ".venv\Scripts\pythonw.exe"
$sti    = "\Familiehub\"

if ($Fjern) {
    Get-ScheduledTask -TaskPath $sti -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
    Write-Host "Alle Familiehub-oppgaver er fjernet."
    return
}

if (-not (Test-Path $python)) { Write-Host "Fant ikke $python"; exit 1 }

$hverdager = @("Monday","Tuesday","Wednesday","Thursday","Friday")
$kjoringer = @(
    @{ Navn = "07.00 morgen";       Tid = "07:00"; Dager = "alle" },
    @{ Navn = "08.00 naa maa du dra"; Tid = "08:00"; Dager = "hverdager" },
    @{ Navn = "08.10 dagbilde";     Tid = "08:10"; Dager = "hverdager" },
    @{ Navn = "15.00 ettermiddag";  Tid = "15:00"; Dager = "alle" },
    @{ Navn = "18.05 kveld";        Tid = "18:05"; Dager = "alle" }
)

$innstillinger = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

$bruker = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

foreach ($k in $kjoringer) {
    if ($k.Dager -eq "hverdager") {
        $utloser = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $hverdager -At $k.Tid
    } else {
        $utloser = New-ScheduledTaskTrigger -Daily -At $k.Tid
    }
    $handling = New-ScheduledTaskAction -Execute $python -Argument "automatisk.py --planlagt $($k.Tid)" -WorkingDirectory $mappe
    Register-ScheduledTask -TaskPath $sti -TaskName $k.Navn -Action $handling -Trigger $utloser `
        -Settings $innstillinger -Principal $bruker -Force | Out-Null
    Write-Host ("Lagt inn: {0,-22} {1}" -f $k.Navn, $k.Dager)
}
Write-Host ""
Write-Host "Ferdig. Se oppgavene i Oppgaveplanlegging under mappen Familiehub."
