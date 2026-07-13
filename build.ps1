# Builds the plugin ZIP, named SeriesGapFinder-<version>.zip using the
# version tuple in __init__.py.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$match = Select-String -Path __init__.py -Pattern 'version\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)'
if (-not $match) { throw 'Could not find the version tuple in __init__.py' }
$g = $match.Matches[0].Groups
$zip = "SeriesGapFinder-$($g[1].Value).$($g[2].Value).$($g[3].Value).zip"

Compress-Archive -Path *.py, plugin-import-name-series_gap_finder.txt `
  -DestinationPath $zip -Force
Write-Host "Built $zip"
