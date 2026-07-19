$startYear = 2014
$endYear = 2024

for ($year = $startYear; $year -le $endYear; $year++) {
    Write-Host "Importing season $year..."
    python espn_history_importer.py $year
    Write-Host "Completed season $year`n"
}

Write-Host "All seasons imported!"