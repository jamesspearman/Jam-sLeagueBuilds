# Creates "Jam's League Builds" shortcuts on your Desktop and in the Start Menu.
# Run it through install.bat (double-click). Run it again if you move this folder.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $here 'launcher.pyw'
$icon = Join-Path $here 'icon.ico'

# Find pythonw.exe (Python without a console window)
$pythonw = $null
foreach ($cmd in @('py', 'python')) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $pyArgs = @()
        if ($cmd -eq 'py') { $pyArgs = @('-3') }
        try {
            $exe = & $cmd @pyArgs -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))" 2>$null
            if ($exe -and (Test-Path $exe.Trim())) { $pythonw = $exe.Trim(); break }
        } catch {}
    }
}
if (-not $pythonw) {
    Write-Host ''
    Write-Host 'Could not find Python (pythonw.exe). Install Python 3 from python.org with'
    Write-Host '"Add python.exe to PATH" ticked, then run install.bat again.'
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    [Environment]::GetFolderPath('Desktop'),
    [Environment]::GetFolderPath('Programs')
)
foreach ($dir in $targets) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "Jam's League Builds.lnk"))
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = '"' + $launcher + '"'
    $lnk.WorkingDirectory = $here
    $lnk.IconLocation = $icon + ',0'
    $lnk.Description = 'Emerald+ builds for any champion'
    $lnk.Save()
    Write-Host "Created shortcut in $dir"
}
Write-Host ''
Write-Host "Done. Open Jam's League Builds from your Desktop or Start Menu."
Write-Host 'Tip: right-click the Start Menu entry and choose "Pin to taskbar".'
