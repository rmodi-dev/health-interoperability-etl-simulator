#Requires -RunAsAdministrator
#Requires -Version 5.1
<#
.SYNOPSIS
    Provisions the lab Hyper-V VM (Generation 2, static RAM, OS + swap + seed disks).
.DESCRIPTION
    Idempotent: existing disks/VM are reused, not overwritten. Every mutation is guarded
    and logged to a transcript. -DryRun runs preflight only and does NOT require the seed
    VHDX to exist yet (it reports seed status instead).

    Disk layout decision: OS disk is DYNAMIC (space-efficient on a laptop SSD) and resized
    to 64 GB; the guest grows the filesystem via cloud-init growpart. Swap disk is FIXED
    4 GB so the guest can discover it by exact byte size. Seed is a small FAT VHDX
    labelled CIDATA (built by build-seed.ps1).
.NOTES
    Clearing the NTFS sparse flag does NOT convert a dynamic VHDX to fixed - it only
    prevents sparse-allocation issues. Compression on the target folder is unsupported
    for VHDX and is removed if detected.
.EXAMPLE
    .\provision-vm.ps1 -DryRun
.EXAMPLE
    .\provision-vm.ps1 -SwitchName 'Default Switch'
#>
[CmdletBinding()]
param(
    [string]$VMName = 'rm-u2604-2611b1',
    [string]$SourceVhdx = 'C:\Downloads\Software\ubuntu-26.04-server-cloudimg-amd64.vhdx',
    [string]$VhdDir = 'C:\ProgramData\Microsoft\Windows\Virtual Hard Disks',
    [string]$VMPath = 'C:\ProgramData\Microsoft\Windows\Hyper-V',
    [string]$SeedVhdx = '',
    [string]$SwitchName = 'RM-VS001',
    [int]$MemoryGB = 8,
    [int]$CpuCount = 4,
    [int]$OsDiskGB = 64,
    [int]$SwapDiskGB = 4,
    [int]$IpWaitSeconds = 180,
    [switch]$NoStart,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step { param([string]$m) Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Write-Note { param([string]$m) Write-Host "   $m" -ForegroundColor Gray }
function Fail       { param([string]$m) throw "PROVISION FAILED: $m" }

if ([string]::IsNullOrWhiteSpace($SeedVhdx)) { $SeedVhdx = Join-Path $VhdDir ($VMName + '-seed.vhdx') }
$OsVhdx   = Join-Path $VhdDir ($VMName + '.vhdx')
$SwapVhdx = Join-Path $VhdDir ($VMName + '-swap.vhdx')

$logDir = Join-Path $PSScriptRoot 'logs'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logPath = Join-Path $logDir ('provision-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
try { Start-Transcript -Path $logPath | Out-Null } catch { Write-Warning "Transcript not started: $_" }

try {
    Write-Step '1/7 Preflight'
    if (-not (Get-Command Get-VM -ErrorAction SilentlyContinue)) { Fail 'Hyper-V PowerShell module not available.' }
    if (-not (Test-Path -LiteralPath $SourceVhdx)) { Fail "Source cloud image not found: $SourceVhdx" }

    $seedStatus = 'NOT BUILT (run build-seed.ps1 before the real run)'
    if (Test-Path -LiteralPath $SeedVhdx) {
        if ((Get-Item -LiteralPath $SeedVhdx).Length -le 0) { Fail 'Seed VHDX exists but is empty.' }
        $seedStatus = 'present'
    } elseif (-not $DryRun) {
        Fail "Seed VHDX not found: $SeedVhdx (run build-seed.ps1 first)."
    } else {
        Write-Warning "Seed VHDX not built yet: $SeedVhdx - normal for a dry run."
    }
    Write-Note "Seed disk : $SeedVhdx ($seedStatus)"

    $srcInfo = Get-VHD -Path $SourceVhdx
    Write-Note ("Source image: {0} ({1}, {2:N1} GB virtual)" -f $SourceVhdx, $srcInfo.VhdType, ($srcInfo.Size / 1GB))

    $sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
    if (-not $sw) {
        Write-Host 'Available switches:' -ForegroundColor Yellow
        Get-VMSwitch | Format-Table Name, SwitchType, NetAdapterInterfaceDescription -AutoSize | Out-Host
        Fail "Virtual switch '$SwitchName' not found. Re-run with -SwitchName '<name>' (e.g. 'Default Switch')."
    }
    Write-Note ("Switch: {0} ({1})" -f $sw.Name, $sw.SwitchType)

    $hostRamGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    if (($MemoryGB + 4) -gt $hostRamGB) { Fail "Host RAM $hostRamGB GB too small for $MemoryGB GB VM + 4 GB headroom." }
    Write-Note "Host RAM: $hostRamGB GB | VM static RAM: $MemoryGB GB | vCPU: $CpuCount"

    $running = @(Get-VM | Where-Object { $_.State -eq 'Running' -and $_.Name -ne $VMName })
    if ($running.Count -gt 0) {
        Write-Warning ('Other running VMs: {0}. Stop them to free RAM, e.g. Stop-VM -Name <name>' -f (($running | ForEach-Object { $_.Name }) -join ', '))
    }

    foreach ($dir in @($VhdDir, $VMPath)) {
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $attrs = [int](Get-Item -LiteralPath $dir).Attributes
        if ($attrs -band [int][System.IO.FileAttributes]::Compressed) {
            Write-Warning "$dir is NTFS-compressed (unsupported for VHDX). Removing compression..."
            & compact.exe /U /S:"$dir" /A /I /F /Q | Out-Host
        }
    }
    $volLetter = (Get-Item -LiteralPath $VhdDir).PSDrive.Name
    $freeGB = [math]::Round((Get-Volume -DriveLetter $volLetter).SizeRemaining / 1GB, 1)
    $needGB = $SwapDiskGB + 12
    if ($freeGB -lt $needGB) { Fail "Volume $volLetter has $freeGB GB free; need at least $needGB GB." }
    Write-Note "Free space on ${volLetter}: $freeGB GB (need >= $needGB GB)"

    if ($DryRun) {
        Write-Step 'DRY RUN - plan only, no changes made'
        Write-Note "VM        : $VMName (Gen2, secure boot MicrosoftUEFICertificateAuthority)"
        Write-Note "OS disk   : $OsVhdx (dynamic, resize to $OsDiskGB GB)"
        Write-Note "Swap disk : $SwapVhdx (fixed $SwapDiskGB GB)"
        Write-Note "Seed disk : $SeedVhdx ($seedStatus)"
        Write-Note "Network   : $SwitchName"
        Write-Host "`nDRY RUN OK" -ForegroundColor Green
        return
    }

    Write-Step '2/7 OS disk'
    if (Test-Path -LiteralPath $OsVhdx) {
        Write-Note 'OS VHDX exists - reusing (no copy/resize).'
    } else {
        Copy-Item -LiteralPath $SourceVhdx -Destination $OsVhdx
        Write-Note 'Copied pristine cloud image.'
    }
    if ([int](Get-Item -LiteralPath $OsVhdx).Attributes -band [int][System.IO.FileAttributes]::SparseFile) {
        & fsutil.exe sparse setflag "$OsVhdx" 0 | Out-Null
        Write-Note 'Cleared NTFS sparse flag.'
    }
    $osInfo = Get-VHD -Path $OsVhdx
    if ($osInfo.Size -lt ($OsDiskGB * 1GB)) {
        if ($osInfo.Attached) { Fail 'OS VHDX is attached; stop the VM before resizing.' }
        Resize-VHD -Path $OsVhdx -SizeBytes ($OsDiskGB * 1GB)
        Write-Note "Resized OS VHDX to $OsDiskGB GB (guest growpart expands the filesystem)."
    } else {
        Write-Note ("OS VHDX already {0:N0} GB." -f ($osInfo.Size / 1GB))
    }

    Write-Step '3/7 Swap disk'
    if (Test-Path -LiteralPath $SwapVhdx) {
        Write-Note 'Swap VHDX exists - reusing.'
    } else {
        New-VHD -Path $SwapVhdx -SizeBytes ($SwapDiskGB * 1GB) -Fixed | Out-Null
        Write-Note "Created fixed $SwapDiskGB GB swap VHDX."
    }

    Write-Step '4/7 Virtual machine'
    $vm = Get-VM -Name $VMName -ErrorAction SilentlyContinue
    if (-not $vm) {
        $vm = New-VM -Name $VMName -Generation 2 -MemoryStartupBytes ($MemoryGB * 1GB) -VHDPath $OsVhdx -Path $VMPath -SwitchName $SwitchName
        Write-Note 'Created Generation 2 VM.'
    } else {
        Write-Note 'VM exists - reusing.'
        if ($vm.State -eq 'Running') { Fail 'VM is running. Stop it before re-running provisioning.' }
    }
    Set-VMProcessor -VMName $VMName -Count $CpuCount
    Set-VMMemory -VMName $VMName -DynamicMemoryEnabled $false -StartupBytes ($MemoryGB * 1GB)
    Set-VM -Name $VMName -AutomaticCheckpointsEnabled $false
    Set-VMFirmware -VMName $VMName -EnableSecureBoot On -SecureBootTemplate 'MicrosoftUEFICertificateAuthority'
    Connect-VMNetworkAdapter -VMName $VMName -SwitchName $SwitchName
    Write-Note 'CPU, static memory, secure boot, checkpoints-off and switch applied.'

    Write-Step '5/7 Attach disks and set boot order'
    $attached = @(Get-VMHardDiskDrive -VMName $VMName | ForEach-Object { $_.Path })
    foreach ($disk in @($OsVhdx, $SwapVhdx, $SeedVhdx)) {
        if ($attached -notcontains $disk) {
            Add-VMHardDiskDrive -VMName $VMName -Path $disk
            Write-Note "Attached: $disk"
        } else {
            Write-Note "Already attached: $disk"
        }
    }
    $osDrive = Get-VMHardDiskDrive -VMName $VMName | Where-Object { $_.Path -eq $OsVhdx }
    Set-VMFirmware -VMName $VMName -FirstBootDevice $osDrive
    $kvp = @(Get-VMIntegrationService -VMName $VMName | Where-Object { $_.Name -like '*Key-Value*' })
    foreach ($s in $kvp) { Enable-VMIntegrationService -VMName $VMName -Name $s.Name }
    Write-Note 'Boot order = OS disk; KVP integration service enabled (needed for IP discovery).'

    Write-Step '6/7 VHDX permissions (defensive)'
    $vmId = (Get-VM -Name $VMName).VMId
    foreach ($disk in @($OsVhdx, $SwapVhdx, $SeedVhdx)) {
        & icacls.exe "$disk" /grant "NT VIRTUAL MACHINE\$($vmId):(F)" | Out-Null
    }
    Write-Note "Granted VM SID $vmId full control on all three VHDX files."

    Write-Step '7/7 Start and discover guest IP'
    if ($NoStart) {
        Write-Note 'NoStart specified - VM left powered off.'
    } else {
        if ((Get-VM -Name $VMName).State -ne 'Running') { Start-VM -Name $VMName; Write-Note 'VM started.' }
        else { Write-Note 'VM already running.' }
        Write-Note 'cloud-init installs/upgrades packages and may reboot once. Allow 5-15 minutes.'
        $deadline = (Get-Date).AddSeconds($IpWaitSeconds)
        $ips = @()
        while ((Get-Date) -lt $deadline) {
            $ips = @(Get-VMNetworkAdapter -VMName $VMName | ForEach-Object { $_.IPAddresses } |
                     Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' })
            if ($ips.Count -gt 0) { break }
            Start-Sleep -Seconds 5
        }
        if ($ips.Count -gt 0) {
            Write-Host ("`nGuest IPv4 (via KVP): {0}" -f ($ips -join ', ')) -ForegroundColor Green
            Write-Note "Try: ssh rmodi@$($ips[0])"
        } else {
            Write-Warning 'No guest IPv4 reported yet. See vm/README.md section "Finding the VM after a network change".'
        }
    }
    Write-Host "`nPROVISION OK - next: run the platform gate in vm/README.md" -ForegroundColor Green
    Write-Note "Log: $logPath"
}
finally {
    try { Stop-Transcript | Out-Null } catch { }
}