# Build a league from scratch: import every season, then generate the
# manager mapping the app's setup screen will ask someone to fill in.
#
#   .\import_all_seasons.ps1                 # 2014 to the current season
#   .\import_all_seasons.ps1 -StartYear 2011 # a longer history
#   .\import_all_seasons.ps1 -StartYear 2018 -EndYear 2023
#
# Seasons are imported independently, so one bad year does not stop the run.
# Very old seasons are sometimes stored by ESPN in a format the underlying
# espn_api library cannot read (see README.md); those are reported at the end
# and simply left out of the dashboard.

param(
    [int]$StartYear = 2014,
    [int]$EndYear = 0
)

if ($EndYear -eq 0) {
    # A fantasy season is named for the year it starts, so before September
    # the most recent complete season is last year.
    $now = Get-Date
    $EndYear = if ($now.Month -ge 9) { $now.Year } else { $now.Year - 1 }
}

Write-Host "Importing seasons $StartYear through $EndYear...`n"

$failed = @()
foreach ($year in $StartYear..$EndYear) {
    Write-Host "Importing season $year..."
    python espn_history_importer.py $year
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Season $year failed - continuing.`n" -ForegroundColor Yellow
        $failed += $year
    } else {
        Write-Host "Completed season $year`n"
    }
}

if ($failed.Count -gt 0) {
    Write-Host "Could not import: $($failed -join ', ')" -ForegroundColor Yellow
}

$imported = ($StartYear..$EndYear | Where-Object { $failed -notcontains $_ })
if ($imported.Count -eq 0) {
    Write-Host "No seasons imported - check LEAGUE_ID and credentials in .env." -ForegroundColor Red
    exit 1
}

Write-Host "`nGenerating manager mapping..."
python generate_manager_mapping.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Could not generate the manager mapping." -ForegroundColor Red
    exit 1
}

Write-Host "`nDone - $($imported.Count) season(s) imported."
Write-Host "Start the app (streamlit run app.py) and it will ask who each"
Write-Host "ESPN account really is. No CSV editing required."
