# =============================================================================
# VIRA Server one-command installer for Windows.
#
#   irm https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.ps1 | iex
#
# Detects Windows, memory, disk, GPU and Docker; downloads VIRA; starts the
# server + worker and pulls the selected Ollama model.
#
# Review first if you prefer:
#   irm .../scripts/install.ps1 -OutFile vira-install.ps1
#   notepad vira-install.ps1
#   powershell -ExecutionPolicy Bypass -File .\vira-install.ps1
# =============================================================================
param(
  [string]$Dir = $env:VIRA_DIR,
  [int]$Port = 0,
  [string]$BindAddress = $env:VIRA_BIND_ADDRESS,
  [string]$Model = $env:VIRA_OLLAMA_MODEL,
  [ValidateSet("auto", "bundled", "host", "remote")]
  [string]$OllamaMode = $(if ($env:VIRA_OLLAMA_MODE) { $env:VIRA_OLLAMA_MODE } else { "auto" }),
  [string]$OllamaUrl = $env:VIRA_OLLAMA_URL,
  [switch]$Gpu,
  [switch]$NoModel,
  [switch]$NoDockerInstall,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoOwner = if ($env:VIRA_REPO_OWNER) { $env:VIRA_REPO_OWNER } else { "Vishalsng112" }
$RepoName = if ($env:VIRA_REPO_NAME) { $env:VIRA_REPO_NAME } else { "VIRA" }
$RepoRef = if ($env:VIRA_REF) { $env:VIRA_REF } else { "main" }

function Write-Step($message) { Write-Host "• $message" -ForegroundColor Cyan }
function Write-Ok($message) { Write-Host "✓ $message" -ForegroundColor Green }
function Write-Warn($message) { Write-Host "! $message" -ForegroundColor Yellow }
function Fail($message) { Write-Host "✕ $message" -ForegroundColor Red; exit 1 }
function Have($command) { return [bool](Get-Command $command -ErrorAction SilentlyContinue) }

if ($env:OS -ne "Windows_NT") {
  Fail "This installer is for Windows. On Linux/macOS use scripts/install.sh."
}

if (-not $Dir) { $Dir = Join-Path $env:USERPROFILE "VIRA" }
if (-not $Port -or $Port -le 0) { $Port = 8000 }
if (-not $BindAddress) { $BindAddress = "0.0.0.0" }

# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------
$arch = if ($env:PROCESSOR_ARCHITECTURE) { $env:PROCESSOR_ARCHITECTURE } else { "unknown" }
try {
  $ramBytes = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
} catch {
  $ramBytes = 0
}
$ramGb = [math]::Floor($ramBytes / 1GB)
$driveLetter = (Resolve-Path $env:USERPROFILE).Path.Substring(0, 1)
try {
  $freeBytes = (Get-PSDrive -Name $driveLetter).Free
} catch {
  $freeBytes = 0
}
$freeGb = [math]::Floor($freeBytes / 1GB)
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
$gpuName = "CPU / integrated"
if (Have "nvidia-smi") {
  try {
    $gpuName = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
  } catch { $gpuName = "NVIDIA GPU" }
}
try {
  $windowsVersion = (Get-CimInstance Win32_OperatingSystem).Caption
} catch {
  $windowsVersion = "Windows"
}

if (-not $Model) {
  if ($ramGb -lt 10) { $Model = "llama3.2:3b" }
  elseif ($ramGb -lt 20) { $Model = "llama3.1:8b" }
  elseif ($ramGb -lt 36) { $Model = "qwen2.5:14b" }
  else { $Model = "qwen2.5:32b" }
}

if ($OllamaMode -eq "auto") { $OllamaMode = "bundled" }
if ($OllamaMode -eq "remote" -and -not $OllamaUrl) {
  Fail "Remote Ollama mode requires -OllamaUrl or VIRA_OLLAMA_URL."
}

Write-Host ""
Write-Host "VIRA Server installer" -ForegroundColor White
Write-Host "Local-first AI runtime · server + worker + Ollama" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  System       $windowsVersion · $arch · $cpu"
Write-Host "  Memory       $ramGb GB RAM"
Write-Host "  Disk         $freeGb GB free"
Write-Host "  GPU          $gpuName"
$modeLabel = $OllamaMode
if ($OllamaUrl) { $modeLabel = "$modeLabel · $OllamaUrl" }
Write-Host "  Ollama       $modeLabel"
Write-Host "  Model        $Model"
Write-Host "  Install dir  $Dir"
Write-Host "  Web console  http://localhost:$Port"
Write-Host ""

if ($ramGb -lt 8) { Write-Warn "Less than 8 GB RAM detected. A 3B model can work, but larger models will be slow." }
if ($freeGb -lt 10) { Write-Warn "Less than 10 GB free disk detected. Models and containers need space." }

if ($DryRun) {
  Write-Ok "Dry run complete. Nothing was installed or changed."
  exit 0
}

# ---------------------------------------------------------------------------
# Docker Desktop
# ---------------------------------------------------------------------------
function Test-Docker {
  if (-not (Have "docker")) { return $false }
  try {
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Wait-Docker {
  for ($i = 0; $i -lt 90; $i++) {
    if (Test-Docker) { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

if (-not (Test-Docker)) {
  if ($NoDockerInstall) {
    Fail "Docker is not usable. Install Docker Desktop and re-run."
  }
  if (-not (Have "winget")) {
    Fail "Docker is required. Install Docker Desktop from https://docs.docker.com/desktop/ and re-run."
  }
  Write-Step "Installing Docker Desktop with winget..."
  & winget install --id Docker.DockerDesktop -e --accept-package-agreements --accept-source-agreements
  $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
  if (Test-Path $dockerExe) {
    Write-Step "Starting Docker Desktop..."
    Start-Process $dockerExe
  } else {
    Write-Warn "Docker Desktop was installed. Start it manually if it is not running."
  }
  if (-not (Wait-Docker)) {
    Fail "Docker Desktop is installed but the engine is not reachable. Start Docker Desktop (and reboot if WSL2 was just enabled), then re-run."
  }
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
  Fail "Docker Compose v2 is required. Update Docker Desktop and re-run."
}
Write-Ok "Docker Desktop is ready"

function Invoke-Compose([string[]]$composeArgs) {
  & docker compose @composeArgs
  if ($LASTEXITCODE -ne 0) { throw "docker compose failed (exit $LASTEXITCODE)" }
}

# ---------------------------------------------------------------------------
# Fetch VIRA
# ---------------------------------------------------------------------------
$composePath = Join-Path $Dir "compose.yaml"
$viraPath = Join-Path $Dir "vira"
if ((Test-Path $composePath) -and (Test-Path $viraPath)) {
  Write-Step "Existing VIRA checkout found at $Dir"
  if ((Test-Path (Join-Path $Dir ".git")) -and (Have "git")) {
    try {
      & git -C $Dir pull --ff-only
    } catch {
      Write-Warn "Could not update the checkout; continuing with existing files."
    }
  }
} else {
  if ((Test-Path $Dir) -and ((Get-ChildItem $Dir -Force | Select-Object -First 1))) {
    Fail "$Dir is not empty and does not look like a VIRA checkout. Choose another -Dir."
  }
  New-Item -ItemType Directory -Path $Dir -Force | Out-Null
  if (Have "git") {
    Write-Step "Downloading VIRA from GitHub ($RepoRef)..."
    & git clone --depth 1 --branch $RepoRef "https://github.com/$RepoOwner/$RepoName.git" $Dir
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed." }
  } else {
    Write-Step "git not found; downloading a source archive..."
    $zip = Join-Path $env:TEMP "vira-$([Guid]::NewGuid().ToString('N')).zip"
    $extract = Join-Path $env:TEMP "vira-extract-$([Guid]::NewGuid().ToString('N'))"
    Invoke-WebRequest -Uri "https://github.com/$RepoOwner/$RepoName/archive/refs/heads/$RepoRef.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $extract -Force
    $inner = Get-ChildItem $extract -Directory | Select-Object -First 1
    if (-not $inner) { Fail "Downloaded archive was empty." }
    Copy-Item (Join-Path $inner.FullName "*") $Dir -Recurse -Force
    Remove-Item $zip, $extract -Recurse -Force -ErrorAction SilentlyContinue
  }
}
if (-not (Test-Path (Join-Path $Dir "compose.yaml"))) {
  Fail "VIRA download did not contain compose.yaml."
}

# ---------------------------------------------------------------------------
# Native Ollama (optional host mode)
# ---------------------------------------------------------------------------
if ($OllamaMode -eq "host") {
  if (-not (Have "ollama")) {
    Write-Step "Installing native Ollama..."
    if (Have "winget") {
      & winget install --id Ollama.Ollama -e --accept-package-agreements --accept-source-agreements
    } else {
      Invoke-Expression (Invoke-RestMethod https://ollama.com/install.ps1)
    }
  }
  [Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
  $env:OLLAMA_HOST = "0.0.0.0:11434"
  if (Have "ollama") {
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 30; $i++) {
      try {
        Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
        break
      } catch { Start-Sleep -Seconds 1 }
    }
  }
  if (-not $OllamaUrl) { $OllamaUrl = "http://host.docker.internal:11434" }
}

# ---------------------------------------------------------------------------
# Configure and start
# ---------------------------------------------------------------------------
Set-Location $Dir
$envPath = Join-Path $Dir ".env"
if (Test-Path $envPath) {
  Write-Step "Keeping existing .env"
} else {
  $lines = @(
    "VIRA_BIND_ADDRESS=$BindAddress",
    "VIRA_PORT=$Port",
    "VIRA_OLLAMA_MODEL=$Model"
  )
  if ($OllamaUrl) { $lines += "VIRA_OLLAMA_URL=$OllamaUrl" }
  Set-Content -Path $envPath -Value $lines -Encoding ASCII
  Write-Ok "Wrote .env"
}

$composeFiles = @()
if ($OllamaMode -eq "bundled") {
  $composeFiles += @("-f", "compose.yaml")
  if ($Gpu) { $composeFiles += @("-f", "compose.gpu.yaml") }
} else {
  $composeFiles += @("-f", "compose.host-ollama.yaml")
}

$env:VIRA_OLLAMA_MODEL = $Model
if ($OllamaUrl) { $env:VIRA_OLLAMA_URL = $OllamaUrl }

Write-Step "Building and starting VIRA Server + worker..."
Invoke-Compose ($composeFiles + @("up", "-d", "--build"))

Write-Step "Waiting for the server..."
$healthy = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    Invoke-WebRequest -Uri "http://127.0.0.1:$Port/livez" -UseBasicParsing -TimeoutSec 3 | Out-Null
    $healthy = $true
    break
  } catch {
    Start-Sleep -Seconds 2
  }
}
if (-not $healthy) {
  Write-Warn "Server did not become healthy. Check logs:"
  Write-Host "  cd $Dir; docker compose $($composeFiles -join ' ') logs --tail=120 vira"
  exit 1
}
Write-Ok "VIRA Server is healthy"

if (-not $NoModel) {
  Write-Step "Pulling model $Model (this can take a while)..."
  if ($OllamaMode -eq "bundled") {
    try {
      Invoke-Compose ($composeFiles + @("--profile", "setup", "run", "--rm", "model-pull"))
    } catch {
      Write-Warn "Could not pull $Model automatically."
      Write-Host "  cd $Dir; docker compose $($composeFiles -join ' ') exec ollama ollama pull $Model"
    }
  } elseif ($OllamaMode -eq "host") {
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { Write-Warn "Could not pull $Model. Run: ollama pull $Model" }
  } else {
    Write-Step "Remote Ollama models must be pulled on the remote host."
  }
}

Write-Host ""
Write-Ok "VIRA Server is ready."
Write-Host ""
Write-Host "  Web console  http://localhost:$Port"
Write-Host "  Install dir  $Dir"
Write-Host "  Logs         cd $Dir; docker compose $($composeFiles -join ' ') logs -f vira worker"
Write-Host "  Stop         cd $Dir; docker compose $($composeFiles -join ' ') down"
Write-Host ""
Write-Host "Next: open the web console and create the admin account."
Write-Host "Then install VIRA Link on each device and use http://<server-LAN-IP>:$Port as its server URL."
