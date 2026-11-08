# Creates a "WitMotion Console" shortcut on the Desktop that runs start-witmotion.bat.
# Usage:  powershell -ExecutionPolicy Bypass -File create-shortcut.ps1
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')   # follows OneDrive redirection
$link = Join-Path $desktop 'WitMotion Console.lnk'

$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = Join-Path $here 'start-witmotion.bat'
$s.WorkingDirectory = $here
$s.IconLocation = (Join-Path $here 'assets\witmotion.ico') + ',0'
$s.Description = 'Start the WitMotion sensor console'
$s.WindowStyle = 1
$s.Save()
Write-Host "Created $link -> $($s.TargetPath)"
