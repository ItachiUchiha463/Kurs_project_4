# Vigil agent installer for Windows (counterpart of install.sh). Run in PowerShell as Administrator:
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/ItachiUchiha463/Kurs_project_4/main/agent/install.ps1))) `
#       -Server https://vigil.example.com -Token vgl_... -HostName web-01
#
# The agent runs as a Task Scheduler task under SYSTEM: it starts at boot (before anyone logs in)
# and is restarted if it fails. Running the script again updates the code and settings.
# Remove: ... -Uninstall
# The file is ASCII on purpose: Windows PowerShell 5.1 reads scripts without BOM in the ANSI code page.
param(
    [string]$Server,
    [string]$Token,
    [string]$HostName,
    [int]$Interval = 15,
    [switch]$Postgres,   # install the PostgreSQL driver (databases are configured in agent.toml, see docs/DEPLOY.md)
    [switch]$NoTask,     # do not create the scheduled task
    [string]$SrcDir,     # take the agent code from a local folder instead of GitHub
    [switch]$Uninstall
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is many times slower with the progress bar
$Repo = 'ItachiUchiha463/Kurs_project_4'
$Ref = if ($env:VIGIL_REF) { $env:VIGIL_REF } else { 'main' }
$Dir = Join-Path $env:ProgramData 'VigilAgent'
$Task = 'VigilAgent'

# throw, not exit: when run through irm | scriptblock, exit would close the administrator's PowerShell window
function Fail([string]$msg) { throw "Vigil agent: $msg" }
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail 'run PowerShell as Administrator' }

function Stop-Agent {
    if (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
    }
    # the task stops python.exe, but a manually started copy from the same folder must also exit before files are replaced
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }
}

if ($Uninstall) {
    Stop-Agent
    if (Get-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $Task -Confirm:$false }
    if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
    Write-Host 'Agent removed.'
    return
}

# the values go into agent.toml: validate them so the file cannot be broken or extended
if ($Server -notmatch '^https?://[A-Za-z0-9.:_/-]+$') { Fail '-Server must look like https://address' }
if ($Token -notmatch '^vgl_[A-Za-z0-9_-]+$') { Fail '-Token must look like vgl_...' }
if (-not $HostName -or $HostName -match "[`"'\\`r`n]") { Fail '-HostName is empty or contains quotes, \ or a line break' }
if ($Interval -lt 15) { Fail '-Interval must be at least 15' }

# Python 3.10+ from python.org: the Microsoft Store alias is per-user and does not work under SYSTEM
$Py = $null
foreach ($c in @(@('py', '-3'), @('python'))) {
    $exe = Get-Command $c[0] -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    $pyArgs = @($c | Select-Object -Skip 1) + @('-c', 'import sys; print(sys.executable) if sys.version_info >= (3, 10) else sys.exit(1)')
    $path = & $exe.Source @pyArgs 2>$null
    if ($LASTEXITCODE -eq 0 -and $path -and $path -notmatch 'WindowsApps') { $Py = $path.Trim(); break }
}
if (-not $Py) { Fail 'Python 3.10 or newer from python.org is required (tick "Add python.exe to PATH" during setup)' }

Stop-Agent
Write-Host 'Downloading the agent code...'
$App = Join-Path $Dir 'app'
New-Item -ItemType Directory -Force -Path $App | Out-Null
if ($SrcDir) {
    Copy-Item (Join-Path $SrcDir 'agent.py') $App -Force
    Copy-Item (Join-Path $SrcDir 'collectors') $App -Recurse -Force
} else {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("vigil-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp 'src.zip'
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/$Ref.zip" -OutFile $zip
        Expand-Archive $zip -DestinationPath $tmp
        $src = Get-ChildItem $tmp -Directory | Select-Object -First 1
        Copy-Item (Join-Path $src.FullName 'agent\agent.py') $App -Force
        Copy-Item (Join-Path $src.FullName 'agent\collectors') $App -Recurse -Force
    } finally { Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
Get-ChildItem $App -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

Write-Host 'Installing dependencies...'
$VenvPy = Join-Path $Dir 'venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    & $Py -m venv (Join-Path $Dir 'venv')
    if ($LASTEXITCODE -ne 0) { Fail 'could not create the virtual environment' }
}
$pkgs = @('psutil', 'httpx')
& $VenvPy -c 'import sys; sys.exit(sys.version_info >= (3, 11))'
if ($LASTEXITCODE -eq 0) { $pkgs += 'tomli' }
if ($Postgres) { $pkgs += 'psycopg[binary]' }
& $VenvPy -m pip install -q --disable-pip-version-check @pkgs
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed' }

# own settings (disks, databases) from an existing agent.toml are kept
$Cfg = Join-Path $App 'agent.toml'
$lines = @("server   = `"$Server`"", "token    = `"$Token`"", "host     = `"$HostName`"", "interval = $Interval",
           'docker   = false  # Docker Desktop on Windows uses npipe; see docs/DEPLOY.md')
if (Test-Path $Cfg) {
    $lines += Get-Content $Cfg -Encoding UTF8 | Where-Object { $_ -notmatch '^\s*(server|token|host|interval|docker)\s*=' }
}
[IO.File]::WriteAllText($Cfg, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))  # tomllib does not accept a BOM
# the token is a secret: only SYSTEM and Administrators may read the file (SIDs, so localized group names do not matter)
& icacls $Cfg /inheritance:r /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null

if ($NoTask) {
    Write-Host "Done. Start manually: cd `"$App`"; & `"$VenvPy`" agent.py --config agent.toml"
    return
}

$Log = Join-Path $Dir 'agent.log'
$action = New-ScheduledTaskAction -Execute $VenvPy -Argument "agent.py --config agent.toml --log `"$Log`"" -WorkingDirectory $App
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $Task -Description 'Vigil monitoring agent' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $Task
Start-Sleep -Seconds 3
$state = (Get-ScheduledTask -TaskName $Task).State
if ($state -ne 'Running') { Fail "the task did not start (state: $state), see $Log" }
Write-Host "Done. The agent is running; the first data will appear in Vigil in about $Interval s."
Write-Host "Log: Get-Content `"$Log`" -Wait   |   remove: ... install.ps1 -Uninstall"
