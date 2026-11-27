# VM Platform Runbook (Stage 0)

Reproducible, Hyper-V platform for the Health Data Interoperability & ETL Simulator.
Scope: **platform only**. Project setup (repo, `.env`, venv, compose) lives in the repo
Makefile from Stage 1 onward.

- Target VM: `rm-u2604-2611b1` — Ubuntu 26.04.1 LTS, Gen2, 8 GB **static** RAM, 4 vCPU
- Disks: OS 64 GB dynamic · swap 4 GB fixed (encrypted in guest) · seed 256 MB FAT/CIDATA
- Access: LAN SSH (key-only) **and** Tailscale tailnet (location-independent)

## 1. Prerequisites

| Requirement                                  | Check                                                                           |
| -------------------------------------------- | ------------------------------------------------------------------------------- |
| Elevated PowerShell 5.1+ with Hyper-V module | `Get-Command Get-VM, Get-VHD`                                                 |
| Ubuntu cloud image VHDX                      | `Test-Path 'C:\Downloads\Software\ubuntu-26.04-server-cloudimg-amd64.vhdx'`   |
| SSH **public** key                     | `Test-Path "$env:USERPROFILE\.ssh\id_rsa.pub"`                                |
| vSwitch                                      | `Get-VMSwitch` (default `RM-VS001`; `Default Switch` is a valid fallback) |
| Tailscale account + auth key (recommended)   | single-use, short expiry, **non-ephemeral**                               |
| ~16 GB free disk, 12 GB free RAM             | checked by the provisioner preflight                                            |

Tailscale auth key: in the admin console generate a key that is **not reusable**
(single use), expires soon (e.g. 1 day), and is **not ephemeral** (the node must
persist). Confirm the exact option labels in your console — wording changes.

## 2. Layout

```
C:\HealthInterop\vm\
├── build-seed.ps1
├── provision-vm.ps1
├── README.md
├── seed\{user-data.yaml, meta-data.yaml}
└── logs\            (transcripts; keep as evidence)
```

These files move into the repo at `vm/` unchanged in Stage 1.

## 3. Execute (elevated PowerShell)

```powershell
cd C:\HealthInterop\vm

# Gate A - parse both scripts BEFORE running them (no execution, syntax only)
foreach ($f in '.\build-seed.ps1', '.\provision-vm.ps1') {
  $errs = $null
  [System.Management.Automation.Language.Parser]::ParseFile(
      (Resolve-Path $f), [ref]$null, [ref]$errs) | Out-Null
  if ($errs) { Write-Host "PARSE ERRORS in $f" -ForegroundColor Red; $errs | Format-List }
  else { Write-Host "PARSE OK: $f" -ForegroundColor Green }
}

# Optional lint (free, PSGallery)
Install-Module PSScriptAnalyzer -Scope CurrentUser -Force
Invoke-ScriptAnalyzer -Path . -Severity Warning, Error

# Gate B - dry runs
.\build-seed.ps1 -DryRun
.\provision-vm.ps1 -DryRun

# Build the seed (hidden prompt keeps the key out of command history)
.\build-seed.ps1 -PromptForAuthKey -Force

# Provision (add -SwitchName 'Default Switch' if RM-VS001 is unavailable)
.\provision-vm.ps1
```

Expected: `SEED BUILD OK`, `PROVISION OK`, and a printed `Guest IPv4 (via KVP)`.
Allow 5–15 minutes; `package_upgrade` may trigger one automatic reboot.

## 4. Finding the VM after a network change

You do **not** need the old IP. Any of these works:

```powershell
# a) Guest-reported IPs (Hyper-V KVP integration service)
Get-VMNetworkAdapter -VMName rm-u2604-2611b1 |
  Format-List Name, SwitchName, Status, MacAddress, IPAddresses

# b) ARP match on the VM MAC (same L2 / Default Switch NAT)
$mac = (Get-VMNetworkAdapter -VMName rm-u2604-2611b1).MacAddress
$dashed = (($mac -split '(..)' | Where-Object { $_ }) -join '-')
Get-NetNeighbor -AddressFamily IPv4 |
  Where-Object { $_.LinkLayerAddress -eq $dashed } |
  Format-Table IPAddress, LinkLayerAddress, State

# c) Tailscale (works on ANY network - the durable answer)
tailscale status          # from the Windows host, same tailnet
ssh rmodi@rm-u2604-2611b1
```

If the external switch is bound to an adapter that no longer exists:

```powershell
Get-NetAdapter | Format-Table Name, InterfaceDescription, Status
Get-VMSwitch  | Format-Table Name, SwitchType, NetAdapterInterfaceDescription
# Rebind (briefly interrupts host networking):
Set-VMSwitch -Name RM-VS001 -NetAdapterName '<active adapter name>'
# Or move the VM to host-NAT networking:
Stop-VM -Name rm-u2604-2611b1
Connect-VMNetworkAdapter -VMName rm-u2604-2611b1 -SwitchName 'Default Switch'
Start-VM -Name rm-u2604-2611b1
```

Guest/corporate Wi-Fi often enables **client isolation**, which blocks host→VM SSH
even with a correct IP. Tailscale is unaffected — that is why it joins at first boot.

## 5. Platform gate (run on the VM after SSH)

```bash
mkdir -p ~/evidence && cd ~/evidence
{
  echo "=== cloud-init ==="
  sudo cloud-init status --long
  sudo cloud-init schema --config-file /var/lib/cloud/instance/user-data.txt --annotate
  echo "=== bootstrap log (tail) ==="
  sudo tail -n 40 /var/log/lab-bootstrap.log
  echo "OK markers: $(sudo grep -c 'PLATFORM BOOTSTRAP OK' /var/log/lab-bootstrap.log)"
  echo "FAIL markers: $(sudo grep -c 'BOOTSTRAP FAILED' /var/log/lab-bootstrap.log)"
  echo "=== toolchain ==="
  docker --version; docker compose version; node --version; uv --version
  uv python list --only-installed
  echo "=== docker daemon smoke ==="
  docker run --rm hello-world
  echo "=== storage / memory ==="
  lsblk; df -h /; swapon --show; free -h
  sysctl vm.overcommit_memory vm.swappiness
  echo "=== network / time ==="
  ip -brief address; sudo ufw status numbered; sudo ss -tlnp
  tailscale status; tailscale ip -4; timedatectl
} 2>&1 | tee ~/evidence/platform-gate-$(date +%Y%m%d-%H%M).log
```

**Pass criteria (all required):**

1. `cloud-init status` → `status: done`, no errors; schema reports **valid**.
2. `OK markers: 1`, `FAIL markers: 0`.
3. `docker compose version` shows **v2**; `docker run --rm hello-world` succeeds
   (proves daemon + group membership; log out/in once if it fails).
4. `node --version` = **v24.22.3**; `uv --version` = **0.13.10**; a uv-managed
   **3.12.x** interpreter listed.
5. `swapon --show` lists `/dev/mapper/cswap` ≈ 4 G; `df -h /` ≈ 63 G.
6. `vm.overcommit_memory = 0`, `vm.swappiness = 10`.
7. `ufw status numbered` shows **only** `22/tcp` and `in on tailscale0` — no
   world-open 8000/2575/8080.
8. `tailscale ip -4` returns a `100.x` address (if an auth key was supplied), and
   `ssh rmodi@rm-u2604-2611b1` works **from the Windows host over the tailnet**.
9. `timedatectl` shows `Africa/Kampala` (+03) and NTP synchronised.

Keep the log — it becomes `docs/evidence/` in Stage 1. Do not claim any result you
have not actually observed.

## 6. Troubleshooting

| Symptom                                                  | Cause / fix                                                                                                                                                                               |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Console login prompt reads `ubuntu login:`             | Seed **not consumed**. Check the seed disk is attached, label is exactly `CIDATA`, and `user-data`/`meta-data` are extensionless at the volume root. Rebuild with `-Force`. |
| Prompt reads `rm-u2604-2611b1 login:` but SSH refused  | Seed applied; bootstrap or network issue. Read the console for `BOOTSTRAP FAILED at line N`, then use KVP/ARP discovery above.                                                          |
| `BOOTSTRAP FAILED` after apt                           | Mirror/network hiccup. Fix connectivity, then `sudo /usr/local/sbin/lab-bootstrap.sh` (idempotent).                                                                                     |
| `no 4294967296-byte data disk found`                   | Swap VHDX missing or not exactly 4 GB. Re-run the provisioner.                                                                                                                            |
| `WARNING: tailnet join failed`                         | Auth key spent/expired. Run `sudo tailscale up --ssh --operator=rmodi` and approve the URL.                                                                                             |
| `docker: permission denied`                            | Group membership needs a fresh login: exit SSH and reconnect.                                                                                                                             |
| Seed build fails on `Format-Volume`                    | Script auto-falls back to FAT16 (still `vfat` to blkid). If both fail, raise `-SeedSizeMB 512`.                                                                                       |
| Provisioner: switch not found                            | Re-run with `-SwitchName 'Default Switch'`.                                                                                                                                             |
| `BUILD-SEED FAILED: Console break-glass hash required` | Generate it: Git Bash → `openssl passwd -6`, then re-run with `-PromptForConsoleHash`.                                                                                               |
| `Start-VM` fails `0x80070005` on the seed LUN after a rebuild | A rebuilt seed is a new file and loses the VM SID ACE. `build-seed.ps1` now re-grants it; if using an older copy, run `.\provision-vm.ps1` (step 6 re-grants) or `icacls <seed.vhdx> /grant "NT VIRTUAL MACHINE\<VMId>:(F)"`. |

## 7. Security notes

- SSH: key-only, root login disabled, password auth off (`sshd_config.d` drop-in).
- The seed VHDX holds a **spendable** Tailscale auth key until first boot; the guest
  deletes it afterwards and locks cloud-init's cached user-data to `0600`. Use a
  single-use, short-expiry key. **Never commit `*.vhdx`** (gitignored from Stage 1).
- Your SSH **private** key never leaves the Windows host.
- App ports will bind `127.0.0.1` in compose — Docker-published ports bypass UFW,
  so loopback binding, not the firewall, is the real control.
- If you typed a secret inline previously, clear history:
  `(Get-PSReadLineOption).HistorySavePath` → delete that file.

## Appendix A — console break-glass password (ENABLED)

Console (VMConnect) password login is enabled for `rmodi` as a recovery path when
SSH and Tailscale are both unavailable. **SSH remains key-only** (`ssh_pwauth: false`
plus the sshd drop-in), so this does not expose password auth to the network.

Generate the hash once, in **Git Bash** (Start Menu → Git Bash):

```bash
command -v openssl        # confirm it exists
openssl passwd -6         # prompts twice; prints $6$<salt>$<86 chars>
```

Copy the printed hash, then supply it at build time:

```powershell
.\build-seed.ps1 -PromptForAuthKey -PromptForConsoleHash -Force
```

Notes:

- Use a long passphrase (12+ chars, printable ASCII). Store it in a password manager.
- The hash lives on the seed VHDX and in the guest's `/etc/shadow`. A SHA-512 crypt
  hash is offline-crackable if leaked — treat the seed VHDX as sensitive.
- The builder validates the hash shape (`$6$…`) and never prints its value.
- If `openssl` is missing in Git Bash, WSL (`openssl passwd -6`) works too. If neither
  is available, say so and I will provide an alternative method.
- To disable later: set `lock_passwd: true`, remove `hashed_passwd`, rebuild the seed,
  bump `instance-id`.
