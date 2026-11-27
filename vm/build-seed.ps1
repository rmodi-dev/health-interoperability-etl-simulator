#Requires -RunAsAdministrator
#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the cloud-init NoCloud seed VHDX (filesystem label CIDATA) for the lab VM.
.DESCRIPTION
    Reads vm/seed/user-data.yaml + meta-data.yaml, substitutes identity/secret tokens,
    and writes them as extensionless LF/UTF-8 (no BOM) files into the root of a small
    FAT-formatted VHDX labelled CIDATA. cloud-init's NoCloud datasource accepts a
    labelled vfat or iso9660 filesystem with user-data and meta-data at its root.

    Token guard: the build FAILS if any __TOKEN__ remains, so a keyless (unreachable)
    VM can never be provisioned by accident.
.NOTES
    Three tokens:
      __SSH_PUBLIC_KEY__        not secret; read from your .pub file
      __TS_AUTHKEY__            SECRET; optional but recommended (single-use key)
      __CONSOLE_PASSWORD_HASH__ SECRET-ish; REQUIRED (console break-glass login)

    Generate the console hash in Git Bash:  openssl passwd -6
    (prompts twice, prints $6$...). Paste it at the -PromptForConsoleHash prompt.
    Prefer the hidden prompts so secrets stay out of PSReadLine history.
    Never commit the seed VHDX or vm/logs.
.EXAMPLE
    .\build-seed.ps1 -DryRun -PromptForAuthKey -PromptForConsoleHash
.EXAMPLE
    .\build-seed.ps1 -PromptForAuthKey -PromptForConsoleHash -Force
#>
[CmdletBinding()]
param(
    [string]$SeedDir = (Join-Path $PSScriptRoot 'seed'),
    [string]$SshPublicKeyPath = (Join-Path $env:USERPROFILE '.ssh\id_rsa.pub'),
    [string]$OutputVhdx = 'C:\ProgramData\Microsoft\Windows\Virtual Hard Disks\rm-u2604-2611b1-seed.vhdx',
    [string]$TailscaleAuthKey = '',
    [switch]$PromptForAuthKey,
    [string]$ConsolePasswordHash = '',
    [switch]$PromptForConsoleHash,
    [int]$SeedSizeMB = 256,
    [switch]$Force,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step { param([string]$m) Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Write-Note { param([string]$m) Write-Host "   $m" -ForegroundColor Gray }
function Fail       { param([string]$m) throw "BUILD-SEED FAILED: $m" }

$logDir = Join-Path $PSScriptRoot 'logs'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logPath = Join-Path $logDir ('build-seed-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
try { Start-Transcript -Path $logPath | Out-Null } catch { Write-Warning "Transcript not started: $_" }

try {
    Write-Step '1/6 Preflight'
    if (-not (Get-Command Get-VHD -ErrorAction SilentlyContinue)) { Fail 'Hyper-V PowerShell module not available.' }
    if ($SeedSizeMB -lt 64 -or $SeedSizeMB -gt 4096) { Fail 'SeedSizeMB must be between 64 and 4096.' }

    $udPath = Join-Path $SeedDir 'user-data.yaml'
    $mdPath = Join-Path $SeedDir 'meta-data.yaml'
    foreach ($p in @($udPath, $mdPath)) {
        if (-not (Test-Path -LiteralPath $p)) { Fail "Missing seed template: $p" }
    }
    if (-not (Test-Path -LiteralPath $SshPublicKeyPath)) { Fail "SSH public key not found: $SshPublicKeyPath" }
    Write-Note "Templates : $SeedDir"
    Write-Note "Public key: $SshPublicKeyPath"
    Write-Note "Output    : $OutputVhdx ($SeedSizeMB MB, fixed)"

    Write-Step '2/6 Read and normalise templates'
    $ud = [System.IO.File]::ReadAllText($udPath)
    $md = [System.IO.File]::ReadAllText($mdPath)
    $ud = ($ud -replace "`r`n", "`n") -replace "`r", "`n"
    $md = ($md -replace "`r`n", "`n") -replace "`r", "`n"
    if (-not $ud.StartsWith('#cloud-config')) { Fail 'user-data.yaml must begin with #cloud-config on line 1.' }
    if ($ud.Contains("`t")) { Fail 'user-data.yaml contains a TAB character (invalid YAML indentation).' }
    if ($md.Contains("`t")) { Fail 'meta-data.yaml contains a TAB character.' }
    if ($ud.Contains('`n')) { Fail 'user-data.yaml contains a literal backtick-n; write real newlines.' }
    if ($md.Contains('`n')) { Fail 'meta-data.yaml contains a literal backtick-n; write real newlines.' }
    if ($md -notmatch '(?m)^instance-id:\s*[A-Za-z0-9._-]+\s*$') {
        Fail 'meta-data.yaml must define a clean instance-id (letters, digits, dot, underscore, hyphen only).'
    }
    Write-Note ("user-data lines: {0} | meta-data lines: {1}" -f $ud.Split("`n").Count, $md.Split("`n").Count)
    Write-Note 'Expected: user-data 246 / meta-data 3 (counts include the trailing newline).'

    Write-Step '3/6 Validate SSH public key'
    $pub = ([System.IO.File]::ReadAllText($SshPublicKeyPath)).Trim()
    if ($pub.Contains("`n")) { Fail 'Public key file must contain exactly one key line.' }
    if ($pub -match 'PRIVATE KEY') { Fail 'That file looks like a PRIVATE key. Refusing to embed it.' }
    if ($pub -notmatch '^(ssh-rsa|ssh-ed25519|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)\s+[A-Za-z0-9+/=]+') {
        Fail 'Unrecognised SSH public key format.'
    }
    $keyType = $pub.Split(' ')[0]
    $keyBits = $pub.Split(' ')[1].Length
    Write-Note "Key type: $keyType (base64 length $keyBits) - fingerprint not printed"

    Write-Step '4/6 Substitute tokens'
    if ($PromptForAuthKey) {
        $sec = Read-Host -Prompt 'Tailscale auth key (hidden; leave empty to skip tailnet join)' -AsSecureString
        $TailscaleAuthKey = [System.Net.NetworkCredential]::new('', $sec).Password
    }
    $envKey = [Environment]::GetEnvironmentVariable('TS_AUTHKEY')
    if ([string]::IsNullOrWhiteSpace($TailscaleAuthKey) -and -not [string]::IsNullOrWhiteSpace($envKey)) {
        $TailscaleAuthKey = $envKey
        Write-Note 'Using TS_AUTHKEY from environment.'
    }

    $tsJoin = $false
    $authValue = ''
    if (-not [string]::IsNullOrWhiteSpace($TailscaleAuthKey)) {
        $k = $TailscaleAuthKey.Trim()
        if ($k -notmatch '^tskey-auth-') { Fail "Tailscale auth key should start with 'tskey-auth-'." }
        $authValue = $k
        $tsJoin = $true
    }

    if ($PromptForConsoleHash) {
        $sec2 = Read-Host -Prompt 'Console password HASH from "openssl passwd -6" (hidden, starts $6$)' -AsSecureString
        $ConsolePasswordHash = [System.Net.NetworkCredential]::new('', $sec2).Password
    }
    $envHash = [Environment]::GetEnvironmentVariable('CONSOLE_PASSWORD_HASH')
    if ([string]::IsNullOrWhiteSpace($ConsolePasswordHash) -and -not [string]::IsNullOrWhiteSpace($envHash)) {
        $ConsolePasswordHash = $envHash
        Write-Note 'Using CONSOLE_PASSWORD_HASH from environment.'
    }
    if ([string]::IsNullOrWhiteSpace($ConsolePasswordHash)) {
        Fail 'Console break-glass hash required. In Git Bash run: openssl passwd -6 ; then re-run with -PromptForConsoleHash.'
    }
    $hash = $ConsolePasswordHash.Trim()
    if ($hash -notmatch '^\$6\$(rounds=\d+\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}$') {
        Fail 'Not a valid SHA-512 crypt hash. Expected $6$<salt>$<86 chars>. Generate with: openssl passwd -6'
    }
    Write-Note 'Console break-glass: ENABLED (hash shape validated; value not printed)'

    $map = @{
        '__SSH_PUBLIC_KEY__'        = $pub
        '__TS_AUTHKEY__'            = $authValue
        '__CONSOLE_PASSWORD_HASH__' = $hash
    }
    foreach ($token in $map.Keys) {
        if (-not $ud.Contains($token)) { Fail "Token $token not found in user-data.yaml (template/version mismatch)." }
        $ud = $ud.Replace($token, $map[$token])
    }
    if ($ud -match '__[A-Z0-9_]+__') { Fail "Unreplaced token remains: $($Matches[0])" }
    if (-not $ud.Contains($pub)) { Fail 'SSH key substitution did not take effect.' }
    if ($tsJoin) { Write-Note 'Tailnet auto-join: ARMED (single-use key expected)' }
    else { Write-Note 'Tailnet auto-join: SKIPPED (run tailscale up manually after first login)' }

    if ($DryRun) {
        Write-Step 'DRY RUN - no disk changes made'
        Write-Note "Would create/recreate: $OutputVhdx"
        Write-Note 'Would write: <seed>:\user-data and <seed>:\meta-data (LF, UTF-8 no BOM)'
        Write-Host "`nDRY RUN OK" -ForegroundColor Green
        return
    }

    Write-Step '5/6 Create and format seed VHDX'
    if (Test-Path -LiteralPath $OutputVhdx) {
        if (-not $Force) { Fail "Seed already exists: $OutputVhdx (re-run with -Force to rebuild)." }
        if ((Get-VHD -Path $OutputVhdx).Attached) { Fail 'Seed VHDX is attached. Stop the VM / detach the disk first.' }
        Remove-Item -LiteralPath $OutputVhdx -Force
        Write-Note 'Removed previous seed VHDX.'
    }
    $parent = Split-Path -Parent $OutputVhdx
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    New-VHD -Path $OutputVhdx -SizeBytes ($SeedSizeMB * 1MB) -Fixed | Out-Null
    Mount-VHD -Path $OutputVhdx
    $diskNumber = (Get-VHD -Path $OutputVhdx).DiskNumber
    if ($null -eq $diskNumber) { Fail 'Mounted seed VHDX reports no disk number.' }
    Initialize-Disk -Number $diskNumber -PartitionStyle MBR -Confirm:$false
    $part = New-Partition -DiskNumber $diskNumber -UseMaximumSize
    $fsUsed = 'FAT32'
    try {
        Format-Volume -Partition $part -FileSystem FAT32 -NewFileSystemLabel 'CIDATA' -Force -Confirm:$false | Out-Null
    } catch {
        Write-Note 'FAT32 format failed on this volume size; falling back to FAT (FAT16).'
        Write-Note 'blkid reports FAT12/16/32 all as TYPE=vfat, which NoCloud accepts.'
        Format-Volume -Partition $part -FileSystem FAT -NewFileSystemLabel 'CIDATA' -Force -Confirm:$false | Out-Null
        $fsUsed = 'FAT'
    }
    $part = Get-Partition -DiskNumber $diskNumber -PartitionNumber $part.PartitionNumber
    if (-not $part.DriveLetter -or [int][char]$part.DriveLetter -eq 0) {
        Add-PartitionAccessPath -DiskNumber $diskNumber -PartitionNumber $part.PartitionNumber -AssignDriveLetter
        Start-Sleep -Seconds 1
        $part = Get-Partition -DiskNumber $diskNumber -PartitionNumber $part.PartitionNumber
    }
    $dl = $part.DriveLetter
    if (-not $dl -or [int][char]$dl -eq 0) { Fail 'Seed volume has no drive letter; cannot write files.' }
    $root = ('{0}:\' -f $dl)
    Write-Note "Seed volume: $root ($fsUsed, label CIDATA)"

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $root 'user-data'), $ud, $utf8NoBom)
    [System.IO.File]::WriteAllText((Join-Path $root 'meta-data'), $md, $utf8NoBom)

    Write-Step '6/6 Verify seed contents'
    $backUd = [System.IO.File]::ReadAllText((Join-Path $root 'user-data'))
    $backMd = [System.IO.File]::ReadAllText((Join-Path $root 'meta-data'))
    if ($backUd -ne $ud) { Fail 'user-data readback differs from intended content.' }
    if ($backMd -ne $md) { Fail 'meta-data readback differs from intended content.' }
    if ($backUd.Contains("`r")) { Fail 'CR byte found in seed user-data (must be LF only).' }
    $vol = Get-Volume -DriveLetter $dl
    if ($vol.FileSystemLabel -ne 'CIDATA') { Fail "Volume label is '$($vol.FileSystemLabel)', must be exactly CIDATA." }
    foreach ($n in @('user-data', 'meta-data')) {
        $len = (Get-Item -LiteralPath (Join-Path $root $n)).Length
        if ($len -le 0) { Fail "$n is empty on the seed." }
        Write-Note ("{0}: {1} bytes" -f $n, $len)
    }
    Write-Note ("Label={0} FileSystem={1} Size={2}MB" -f $vol.FileSystemLabel, $vol.FileSystem, $SeedSizeMB)
    # A rebuilt seed is a NEW file: it inherits folder ACLs and LOSES the per-VM
    # SID ACE Hyper-V needs. Re-grant it, else Start-VM fails with 0x80070005.
    $granted = 0
    foreach ($v in @(Get-VM -ErrorAction SilentlyContinue)) {
        $paths = @(Get-VMHardDiskDrive -VMName $v.Name -ErrorAction SilentlyContinue | ForEach-Object { $_.Path })
        if ($paths -contains $OutputVhdx) {
            & icacls.exe "$OutputVhdx" /grant "NT VIRTUAL MACHINE\$($v.VMId):(F)" | Out-Null
            Write-Note "Re-granted VM SID $($v.VMId) on new seed (VM: $($v.Name))"
            $granted++
        }
    }
    if ($granted -eq 0) { Write-Note 'No VM references this seed yet; provision-vm.ps1 grants on first run.' }
    Write-Host "`nSEED BUILD OK -> $OutputVhdx" -ForegroundColor Green
    Write-Warning 'This seed VHDX holds a console password hash and (if armed) a spendable Tailscale key until first boot. Keep it private; never commit it.'
    Write-Note "Log: $logPath"
}
finally {
    if (Test-Path -LiteralPath $OutputVhdx) {
        try {
            if ((Get-VHD -Path $OutputVhdx).Attached) { Dismount-VHD -Path $OutputVhdx }
        } catch { Write-Warning "Could not dismount seed VHDX: $_" }
    }
    try { Stop-Transcript | Out-Null } catch { }
}