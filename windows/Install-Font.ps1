param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$Url = 'https://github.com/ryanoasis/nerd-fonts/releases/download/v3.5.1/JetBrainsMono.zip'
$Expected = 'fab782a66f7d3019da64f6572db9fc5d3a4bcb19f9fa13e2d8a62e3693d6396e'
$Destination = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts\terminal-kit'
if (!$Apply) {
    Write-Host "Preview: install verified Nerd Fonts v3.5.1 JetBrains Mono per-user in $Destination."
    Write-Host 'Run this script with -Apply, then restart Windows Terminal and choose JetBrainsMono Nerd Font.'
    exit 0
}
$Temporary = Join-Path ([IO.Path]::GetTempPath()) ('terminal-kit-font-' + [Guid]::NewGuid())
New-Item -ItemType Directory $Temporary | Out-Null
try {
    $Archive = Join-Path $Temporary 'font.zip'
    Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing
    if ((Get-FileHash -Algorithm SHA256 $Archive).Hash.ToLowerInvariant() -ne $Expected) {
        throw 'Font archive checksum mismatch; no fonts installed.'
    }
    Expand-Archive $Archive (Join-Path $Temporary 'fonts')
    New-Item -ItemType Directory -Force $Destination | Out-Null
    $Registry = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
    New-Item -Path $Registry -Force | Out-Null
    $Fonts = @(Get-ChildItem (Join-Path $Temporary 'fonts') -Filter '*.ttf')
    foreach ($Font in $Fonts) {
        $Target = Join-Path $Destination $Font.Name
        if ((Test-Path $Target) -and ((Get-FileHash $Target).Hash -ne (Get-FileHash $Font.FullName).Hash)) {
            throw "Existing font differs: $Target"
        }
        $Name = $Font.BaseName + ' (TrueType)'
        $Existing = (Get-ItemProperty -Path $Registry).PSObject.Properties[$Name]
        if ($null -ne $Existing -and $Existing.Value -ne $Target) {
            throw "Existing Windows font registration differs: $Name. No registrations were changed."
        }
    }
    foreach ($Font in $Fonts) {
        $Target = Join-Path $Destination $Font.Name
        Copy-Item $Font.FullName $Target
        New-ItemProperty -Path $Registry -Name ($Font.BaseName + ' (TrueType)') -Value $Target -PropertyType String -Force | Out-Null
    }
    Get-ChildItem (Join-Path $Temporary 'fonts') -File | Where-Object { $_.Name -match 'LICENSE|OFL' } | Copy-Item -Destination $Destination
    Write-Host 'Fonts installed for this Windows user. Restart Windows Terminal to verify rendering.'
} finally {
    Remove-Item -Recurse -Force $Temporary
}
