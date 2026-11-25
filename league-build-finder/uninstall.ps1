# Removes the shortcuts made by install.bat and the app window's saved settings.
$names = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "Jam's League Builds.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "Jam's League Builds.lnk")
)
foreach ($n in $names) { if (Test-Path $n) { Remove-Item $n; Write-Host "Removed $n" } }
$profileDir = Join-Path $env:LOCALAPPDATA 'JamsLeagueBuilds'
if (Test-Path $profileDir) { Remove-Item $profileDir -Recurse -Force -ErrorAction SilentlyContinue; Write-Host "Removed $profileDir" }
Write-Host 'Done. You can now delete this folder too if you like.'
