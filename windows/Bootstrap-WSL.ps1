param([string]$Distribution = "Ubuntu")
$ErrorActionPreference = 'Stop'
Write-Host 'Run these stages on a fresh Windows machine:'
Write-Host ('1. In Administrator PowerShell: wsl --install --distribution "{0}"' -f $Distribution)
Write-Host '2. Reboot if Windows requests it. Open the distribution and create a Linux user.'
Write-Host '3. Confirm WSL2: wsl --list --verbose'
Write-Host '4. Run the README bootstrap inside that distribution as the Linux user.'
Write-Host '5. For Windows Terminal: terminal-kit windows-host --apply'
Write-Host 'Projects belong in the Linux home directory. This guide does not change Windows settings or reboot.'
