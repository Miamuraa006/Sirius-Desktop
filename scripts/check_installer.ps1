param([Parameter(Mandatory=$true)][string]$SetupPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$checkRoot = Join-Path $projectRoot 'checks\installer-smoke'
$runId = ([guid]::NewGuid().ToString('N')).Substring(0,6)
$installRoot = Join-Path $checkRoot ("app-$runId")
$protectedRoot = Join-Path $checkRoot 'keep-existing'
$profileRoot = Join-Path $checkRoot ("profile-$runId")
$report = [ordered]@{ passed=$false; checks=[ordered]@{} }
New-Item -ItemType Directory -Path $checkRoot,$protectedRoot -Force | Out-Null
Set-Content -LiteralPath (Join-Path $protectedRoot 'keep.txt') -Value 'Existing user file'
$desktopLink = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Sirius.lnk'
$desktopHash = if(Test-Path -LiteralPath $desktopLink) { (Get-FileHash -LiteralPath $desktopLink).Hash } else { $null }
function Run-Setup([string]$Destination) {
    $p=Start-Process -FilePath $SetupPath -ArgumentList "/silent /test `"/dir=$Destination`"" -WindowStyle Hidden -PassThru
    if(-not $p.WaitForExit(45000)) {throw 'Setup timeout'}
    return $p.ExitCode
}
function Check([string]$Name,[bool]$Passed) {
    $report.checks[$Name]=$Passed
    if(-not $Passed) {throw "Check failed: $Name"}
    Write-Output "PASS: $Name"
}
try {
    Check 'occupied_folder_rejected' ((Run-Setup $protectedRoot) -eq 1 -and (Get-Content (Join-Path $protectedRoot 'keep.txt')) -eq 'Existing user file')
    Check 'installation_exit_zero' ((Run-Setup $installRoot) -eq 0)
    Check 'installed_executable' (Test-Path -LiteralPath (Join-Path $installRoot 'Sirius.exe'))
    Check 'portable_marker_absent' (-not(Test-Path -LiteralPath (Join-Path $installRoot 'portable.marker')))
    $testName='Sirius (проверка установки)'
    $links=@((Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) "$testName.lnk"),(Join-Path ([Environment]::GetFolderPath('Programs')) "$testName\Sirius.lnk"))
    $shell=New-Object -ComObject WScript.Shell
    foreach($link in $links) {
        Check ('shortcut_exists_' + [IO.Path]::GetFileName($link)) (Test-Path -LiteralPath $link)
        $shortcut=$shell.CreateShortcut($link)
        Check ('shortcut_target_' + [IO.Path]::GetFileName($link)) ($shortcut.TargetPath -eq (Join-Path $installRoot 'Sirius.exe') -and $shortcut.IconLocation -like '*sirius.ico,0')
    }
    $key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Sirius.InstallationTest'
    Check 'windows_uninstall_registration' ((Get-ItemProperty -LiteralPath $key).InstallLocation -eq $installRoot)
    $exe=Join-Path $installRoot 'Sirius.exe'
    $info=[Diagnostics.ProcessStartInfo]::new($exe)
    $info.UseShellExecute=$false;$info.CreateNoWindow=$true
    $info.EnvironmentVariables['LOCALAPPDATA']=$profileRoot
    $info.Arguments='--diagnose --report "'+(Join-Path $checkRoot 'installed-diagnose.json')+'"'
    $app=[Diagnostics.Process]::Start($info)
    if(-not $app.WaitForExit(30000)){throw 'Installed app diagnosis timeout'}
    Check 'installed_diagnose_exit_zero' ($app.ExitCode -eq 0)
    $diagnose=Get-Content (Join-Path $checkRoot 'installed-diagnose.json') -Raw | ConvertFrom-Json
    Check 'installed_resources_and_skills' ($diagnose.passed -and $diagnose.frozen)
    $dataRoot=Join-Path $profileRoot 'Sirius\UserData'
    Check 'installed_profile_location' (Test-Path -LiteralPath (Join-Path $dataRoot 'config.json'))
    $info.Arguments='--help-check-output "'+(Join-Path $checkRoot 'gui')+'" --data-dir "'+$dataRoot+'"'
    $app=[Diagnostics.Process]::Start($info)
    if(-not $app.WaitForExit(30000)){throw 'Installed GUI timeout'}
    $gui=Get-Content (Join-Path $checkRoot 'gui\report.json') -Raw | ConvertFrom-Json
    Check 'installed_gui_help' ($app.ExitCode -eq 0 -and $gui.passed -and $gui.shutdown_clean)
    $configHash=(Get-FileHash -LiteralPath (Join-Path $dataRoot 'config.json')).Hash
    Set-Content -LiteralPath (Join-Path $installRoot 'user-file.txt') -Value 'Preserve this untracked file'
    $uninstall=Start-Process -FilePath (Join-Path $installRoot 'Uninstall.exe') -ArgumentList '/silent' -WindowStyle Hidden -PassThru
    if(-not $uninstall.WaitForExit(15000)){throw 'Uninstall launcher timeout'}
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    while((Test-Path -LiteralPath $key) -and [DateTime]::UtcNow -lt $deadline){Start-Sleep -Milliseconds 250}
    Check 'uninstaller_removed_known_files' (-not(Test-Path -LiteralPath $exe) -and -not(Test-Path -LiteralPath (Join-Path $installRoot 'Uninstall.exe')) -and -not(Test-Path -LiteralPath (Join-Path $installRoot 'install.files')))
    Check 'uninstaller_removed_registration' (-not(Test-Path -LiteralPath $key))
    Check 'uninstaller_removed_shortcuts' (-not(Test-Path -LiteralPath $links[0]) -and -not(Test-Path -LiteralPath $links[1]))
    Check 'uninstaller_preserved_profile' ((Get-FileHash -LiteralPath (Join-Path $dataRoot 'config.json')).Hash -eq $configHash)
    Check 'uninstaller_preserved_untracked_file' ((Get-Content -LiteralPath (Join-Path $installRoot 'user-file.txt')) -eq 'Preserve this untracked file')
    Check 'existing_desktop_shortcut_preserved' ((Get-FileHash -LiteralPath $desktopLink).Hash -eq $desktopHash)
    $report.passed=$true
} finally {
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $checkRoot 'report.json') -Encoding utf8
}
