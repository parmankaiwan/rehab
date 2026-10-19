$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $projectRoot "START FLEXMAP.cmd"
if (-not (Test-Path -LiteralPath $launcher)) { throw "FlexMap launcher was not found: $launcher" }

# The previous logon task started a hardware agent independently and could
# compete with the integrated supervisor for camera/serial ownership.
$legacy = Get-ScheduledTask -TaskName "FlexMap Hardware Agent" -ErrorAction SilentlyContinue
if ($legacy) {
    Stop-ScheduledTask -TaskName "FlexMap Hardware Agent" -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "FlexMap Hardware Agent" -Confirm:$false
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "START FLEXMAP.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Start the integrated FlexMap application"
$shortcut.Save()
Write-Host "Created $shortcutPath"
Write-Host "FlexMap now starts only when you open this shortcut; it is not started automatically at Windows logon."
