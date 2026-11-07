param([string]$PythonPath, [switch]$SkipShortcut)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $sourceRoot
$desktopRoot = Split-Path -Parent $projectRoot
if (-not $PythonPath) { $PythonPath = Join-Path $sourceRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Create .venv or specify -PythonPath.' }
Set-Location -LiteralPath $sourceRoot
$previousPath = $env:PATH
try {
# Package only the application's dependencies; avoid unrelated tool DLLs on PATH.
$env:PATH = "$env:WINDIR\System32;$env:WINDIR;$(Split-Path -Parent $PythonPath)"
$qsb = Join-Path (Split-Path -Parent $PythonPath) 'pyside6-qsb.exe'
& $qsb --glsl '100 es,120,150' --hlsl 50 --msl 12 -o 'ui\shaders\energy.frag.qsb' 'ui\shaders\energy.frag'
if ($LASTEXITCODE) { throw 'Shader compilation failed' }
& $PythonPath -m PyInstaller --clean --noconfirm --distpath $projectRoot --workpath (Join-Path $projectRoot 'checks\build') 'packaging\sirius.spec'
if ($LASTEXITCODE) { throw 'Application build failed' }
Set-Content -LiteralPath (Join-Path $projectRoot 'app\portable.marker') -Value 'Sirius Desktop: keep this edition data beside app.' -Encoding utf8
if (-not $SkipShortcut) {
$shortcuts = New-Object -ComObject WScript.Shell
$shortcut = $shortcuts.CreateShortcut((Join-Path $desktopRoot 'Sirius.lnk'))
$shortcut.TargetPath = Join-Path $projectRoot 'app\Sirius.exe'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = (Join-Path $projectRoot 'app\_internal\ui\assets\sirius.ico') + ',0'
$shortcut.Description = 'Sirius — помощник рабочего стола'
$shortcut.Save()
Write-Output "Ready: $desktopRoot\Sirius.lnk"
}
} finally { $env:PATH = $previousPath }
