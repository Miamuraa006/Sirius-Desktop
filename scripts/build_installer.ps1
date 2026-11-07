param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$projectRoot = Split-Path -Parent $sourceRoot
$desktopRoot = Split-Path -Parent $projectRoot
$buildRoot = Join-Path $projectRoot 'checks\installer-build'
$releaseRoot = Join-Path $desktopRoot 'Sirius — для друзей'
New-Item -ItemType Directory -Path $buildRoot,$releaseRoot -Force | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$refs = @('/nologo','/target:winexe','/platform:x64','/optimize+', '/r:System.IO.Compression.dll', '/r:System.IO.Compression.FileSystem.dll', '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:Microsoft.CSharp.dll')
$icon = Join-Path $sourceRoot 'ui\assets\sirius.ico'
$manifest = Join-Path $sourceRoot 'packaging\windows.manifest'
$core = Join-Path $sourceRoot 'packaging\InstallCore.cs'
$uninstall = Join-Path $buildRoot 'Uninstall.exe'
& $compiler @refs "/out:$uninstall" "/win32icon:$icon" "/win32manifest:$manifest" (Join-Path $sourceRoot 'packaging\Uninstall.cs') $core
if ($LASTEXITCODE) { throw 'Uninstaller compilation failed' }
& $PythonPath (Join-Path $PSScriptRoot 'package_payload.py') (Join-Path $projectRoot 'app') $uninstall $buildRoot
if ($LASTEXITCODE) { throw 'Payload verification failed' }
$setup = Join-Path $releaseRoot 'Sirius-Setup-0.5.1.exe'
$payload = Join-Path $buildRoot 'payload.zip'
$hashes = Join-Path $buildRoot 'files.sha256'
& $compiler @refs "/out:$setup" "/win32icon:$icon" "/win32manifest:$manifest" "/resource:$payload,payload.zip" "/resource:$hashes,files.sha256" "/resource:$(Join-Path $sourceRoot 'ui\assets\sirius-icon.png'),brand.png" (Join-Path $sourceRoot 'packaging\Setup.cs') $core
if ($LASTEXITCODE) { throw 'Setup compilation failed' }
Copy-Item -LiteralPath (Join-Path $sourceRoot 'packaging\README_RU.txt') -Destination (Join-Path $releaseRoot 'ПРОЧИТАЙ МЕНЯ.txt') -Force
$checksum = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath (Join-Path $releaseRoot 'SHA256SUMS.txt') -Value "$checksum  Sirius-Setup-0.5.1.exe" -Encoding ascii
Write-Output "Ready: $setup"
