#!/usr/bin/env bash
# =============================================================================
# VIRA Server one-command installer for Linux and macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/Vishalsng112/VIRA/main/scripts/install.sh | bash
#
# It detects the OS, architecture, memory, disk and GPU, checks Docker/Ollama,
# downloads VIRA, chooses a model, starts the server + worker and pulls the model.
#
# Review first if you prefer:
#   curl -fsSL .../scripts/install.sh -o vira-install.sh
#   less vira-install.sh
#   bash vira-install.sh
# =============================================================================
set -euo pipefail

REPO_OWNER="${VIRA_REPO_OWNER:-Vishalsng112}"
REPO_NAME="${VIRA_REPO_NAME:-VIRA}"
REPO_REF="${VIRA_REF:-main}"
REPO_URL="${VIRA_REPO_URL:-https://github.com/${REPO_OWNER}/${REPO_NAME}.git}"
ARCHIVE_URL="${VIRA_ARCHIVE_URL:-https://github.com/${REPO_OWNER}/${REPO_NAME}/archive/refs/heads/${REPO_REF}.tar.gz}"
INSTALL_DIR="${VIRA_DIR:-$HOME/vira}"
PORT="${VIRA_PORT:-8000}"
BIND_ADDRESS="${VIRA_BIND_ADDRESS:-0.0.0.0}"
MODE="${VIRA_OLLAMA_MODE:-auto}"
MODEL="${VIRA_OLLAMA_MODEL:-}"
OLLAMA_URL="${VIRA_OLLAMA_URL:-}"
DRY_RUN="${VIRA_DRY_RUN:-0}"
NO_MODEL="${VIRA_NO_MODEL:-0}"
NO_DOCKER_INSTALL="${VIRA_NO_DOCKER_INSTALL:-0}"
NO_OLLAMA_INSTALL="${VIRA_NO_OLLAMA_INSTALL:-0}"
FORCE_GPU="${VIRA_GPU:-0}"

COLOR=1
if [ ! -t 1 ] || [ "${NO_COLOR:-}" ]; then COLOR=0; fi
if [ "$COLOR" = 1 ]; then
  B=$'\033[1m'; DIM=$'\033[2m'; BLUE=$'\033[38;5;33m'; GREEN=$'\033[38;5;35m'
  YELLOW=$'\033[38;5;214m'; RED=$'\033[38;5;196m'; RESET=$'\033[0m'
else
  B=''; DIM=''; BLUE=''; GREEN=''; YELLOW=''; RED=''; RESET=''
fi

say()  { printf '%s\n' "$*"; }
info() { printf '%s•%s %s\n' "$BLUE" "$RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()  { printf '%s✕%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

usage() {
  cat <<EOF
${B}VIRA Server installer${RESET}

Usage:
  curl -fsSL .../scripts/install.sh | bash
  bash install.sh [options]

Options:
  --dir <path>            Install directory (default: \$HOME/vira)
  --port <port>           Host port (default: 8000)
  --bind <address>        Bind address (default: 0.0.0.0; use 127.0.0.1 for local only)
  --model <name>          Ollama model (default: chosen from available RAM)
  --bundled-ollama        Run Ollama in Docker (default on Linux)
  --host-ollama           Use native Ollama on the host (default on macOS)
  --ollama-url <url>      Use an existing/remote Ollama endpoint
  --gpu                   Enable NVIDIA GPU override for bundled Ollama
  --no-model              Do not pull the model
  --no-docker-install     Do not install Docker automatically
  --no-ollama-install     Do not install native Ollama automatically
  --dry-run               Detect and print the plan, change nothing
  --yes                   Non-interactive (accepted for compatibility)
  -h, --help              Show this help

Environment equivalents:
  VIRA_DIR, VIRA_PORT, VIRA_BIND_ADDRESS, VIRA_OLLAMA_MODE,
  VIRA_OLLAMA_MODEL, VIRA_OLLAMA_URL, VIRA_GPU,
  VIRA_NO_MODEL, VIRA_NO_DOCKER_INSTALL, VIRA_NO_OLLAMA_INSTALL
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) INSTALL_DIR="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --bind) BIND_ADDRESS="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --bundled-ollama) MODE="bundled"; shift ;;
    --host-ollama) MODE="host"; shift ;;
    --ollama-url) OLLAMA_URL="$2"; MODE="remote"; shift 2 ;;
    --gpu) FORCE_GPU="1"; shift ;;
    --no-model) NO_MODEL="1"; shift ;;
    --no-docker-install) NO_DOCKER_INSTALL="1"; shift ;;
    --no-ollama-install) NO_OLLAMA_INSTALL="1"; shift ;;
    --dry-run) DRY_RUN="1"; shift ;;
    --yes) :; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (use --help)" ;;
  esac
done

# ---------------------------------------------------------------------------
# Detect host
# ---------------------------------------------------------------------------
UNAME_S="$(uname -s)"
ARCH="$(uname -m)"
case "$UNAME_S" in
  Linux) OS_FAMILY="linux" ;;
  Darwin) OS_FAMILY="macos" ;;
  *) die "This installer supports Linux and macOS. On Windows use install.ps1." ;;
esac

DISTRO="Linux"
DISTRO_VERSION=""
if [ "$OS_FAMILY" = "linux" ] && [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  DISTRO="${NAME:-Linux}"
  DISTRO_VERSION="${VERSION_ID:-}"
fi
if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
  DISTRO="$DISTRO (WSL)"
fi

if [ "$OS_FAMILY" = "macos" ]; then
  RAM_BYTES=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) ))
  CPU_CORES="$(sysctl -n hw.ncpu 2>/dev/null || echo 1)"
  DISK_AVAIL_KB=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
  GPU_NAME="Apple / integrated"
  if sysctl -n machdep.cpu.brand_string 2>/dev/null | grep -qi apple; then
    GPU_NAME="Apple Silicon (Metal)"
  fi
else
  RAM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)
  RAM_BYTES=$(( RAM_KB * 1024 ))
  CPU_CORES=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)
  DISK_AVAIL_KB=$(df -Pk "$HOME" | awk 'NR==2 {print $4}')
  GPU_NAME="CPU / integrated"
  if have nvidia-smi; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || echo "NVIDIA GPU")
  elif have rocm-smi; then
    GPU_NAME=$(rocm-smi --showproductname 2>/dev/null | head -n3 | tr '\n' ' ' || echo "AMD GPU")
  fi
fi

RAM_GB=$(( RAM_BYTES / 1024 / 1024 / 1024 ))
DISK_GB=$(( DISK_AVAIL_KB / 1024 / 1024 ))

if [ -z "$MODEL" ]; then
  if [ "$RAM_GB" -lt 8 ]; then
    MODEL="llama3.2:3b"
  elif [ "$RAM_GB" -lt 20 ]; then
    MODEL="qwen3.5:9b"
  elif [ "$RAM_GB" -lt 36 ]; then
    MODEL="qwen2.5:14b"
  else
    MODEL="qwen2.5:32b"
  fi
fi

if [ "$MODE" = "auto" ]; then
  if [ "$OS_FAMILY" = "macos" ]; then MODE="host"; else MODE="bundled"; fi
fi
if [ "$MODE" = "remote" ] && [ -z "$OLLAMA_URL" ]; then
  die "Remote Ollama mode requires --ollama-url or VIRA_OLLAMA_URL."
fi
if [ "$MODE" = "host" ] && [ "$OS_FAMILY" = "macos" ]; then
  : # Metal-capable native Ollama is the right default here.
fi

GPU_OVERRIDE=0
if [ "$FORCE_GPU" = "1" ]; then
  GPU_OVERRIDE=1
elif [ "$OS_FAMILY" = "linux" ] && have nvidia-smi; then
  # Only use the GPU compose override when Docker reports an NVIDIA runtime.
  if have docker && docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -qi nvidia; then
    GPU_OVERRIDE=1
  fi
fi

say ""
say "${B}VIRA Server installer${RESET}"
say "${DIM}Local-first AI runtime · server + worker + Ollama${RESET}"
say ""
say "  ${B}System${RESET}       ${DISTRO} ${DISTRO_VERSION} · ${ARCH} · ${CPU_CORES} CPU cores"
say "  ${B}Memory${RESET}       ${RAM_GB} GB RAM"
say "  ${B}Disk${RESET}         ${DISK_GB} GB free"
say "  ${B}GPU${RESET}          ${GPU_NAME}"
say "  ${B}Ollama${RESET}       ${MODE}${OLLAMA_URL:+ · $OLLAMA_URL}"
say "  ${B}Model${RESET}        ${MODEL}"
say "  ${B}Install dir${RESET}  ${INSTALL_DIR}"
say "  ${B}Web console${RESET}  http://localhost:${PORT}"
say ""

if [ "$RAM_GB" -lt 8 ]; then
  warn "Less than 8 GB RAM detected. A 3B model can work, but larger models will be slow."
fi
if [ "$DISK_GB" -lt 10 ]; then
  warn "Less than 10 GB free disk detected. Models and containers need space."
fi
if [ "$MODE" = "host" ] && [ "$OS_FAMILY" = "macos" ]; then
  info "macOS: native Ollama is preferred so it can use Metal instead of the Docker Linux VM."
fi

if [ "$DRY_RUN" = "1" ]; then
  say ""
  ok "Dry run complete. Nothing was installed or changed."
  exit 0
fi

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------
DOCKER=()

detect_docker() {
  if ! have docker; then return 1; fi
  if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
    return 0
  fi
  if [ "$(id -u)" -eq 0 ]; then
    DOCKER=(docker)
    return 0
  fi
  if have sudo && sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
    return 0
  fi
  return 1
}

install_docker_linux() {
  [ "$NO_DOCKER_INSTALL" = "1" ] && die "Docker is not usable. Install Docker Engine and re-run."
  info "Docker is required. Installing Docker Engine via get.docker.com..."
  if [ "$(id -u)" -eq 0 ]; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker >/dev/null 2>&1 || true
  else
    curl -fsSL https://get.docker.com | sudo sh
    sudo systemctl enable --now docker >/dev/null 2>&1 || true
    sudo usermod -aG docker "$USER" >/dev/null 2>&1 || true
  fi
  if ! detect_docker; then
    if have sudo; then
      DOCKER=(sudo docker)
    else
      die "Docker installed but the daemon is not reachable. Start Docker and re-run."
    fi
  fi
}

install_docker_macos() {
  [ "$NO_DOCKER_INSTALL" = "1" ] && die "Docker is not usable. Install Docker Desktop, OrbStack or Colima and re-run."
  if have brew; then
    info "Installing Docker Desktop with Homebrew..."
    brew install --cask docker
    open -a Docker >/dev/null 2>&1 || true
    info "Waiting for Docker Desktop to start..."
    for _ in $(seq 1 60); do
      if docker info >/dev/null 2>&1; then break; fi
      sleep 2
    done
  else
    die "Install Docker Desktop for macOS (https://docs.docker.com/desktop/) and re-run."
  fi
  detect_docker || die "Docker is installed but not running. Open Docker Desktop and re-run."
}

if ! detect_docker; then
  if [ "$OS_FAMILY" = "linux" ]; then install_docker_linux; else install_docker_macos; fi
fi
if ! "${DOCKER[@]}" compose version >/dev/null 2>&1; then
  die "Docker Compose v2 is required. Install the Docker Compose plugin and re-run."
fi
ok "Docker $(docker --version 2>/dev/null | sed 's/^Docker version //;s/,.*//') · Compose ready"

compose() { "${DOCKER[@]}" compose "$@"; }

# ---------------------------------------------------------------------------
# Fetch VIRA
# ---------------------------------------------------------------------------
fetch_vira() {
  if [ -f "$INSTALL_DIR/compose.yaml" ] && [ -d "$INSTALL_DIR/vira" ]; then
    info "Existing VIRA checkout found at $INSTALL_DIR"
    if [ -d "$INSTALL_DIR/.git" ] && have git; then
      info "Updating existing checkout..."
      git -C "$INSTALL_DIR" pull --ff-only || warn "Could not update; continuing with existing files."
    fi
    return 0
  fi
  if [ -e "$INSTALL_DIR" ] && [ "$(ls -A "$INSTALL_DIR" 2>/dev/null | head -n1)" ]; then
    die "$INSTALL_DIR is not empty and does not look like a VIRA checkout. Choose another --dir."
  fi
  mkdir -p "$INSTALL_DIR"
  if have git; then
    info "Downloading VIRA from GitHub ($REPO_REF)..."
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
  else
    info "git not found; downloading a release archive..."
    curl -fsSL "$ARCHIVE_URL" | tar -xz --strip-components=1 -C "$INSTALL_DIR"
  fi
}
fetch_vira
[ -f "$INSTALL_DIR/compose.yaml" ] || die "VIRA download did not contain compose.yaml."

# ---------------------------------------------------------------------------
# Native Ollama (host mode)
# ---------------------------------------------------------------------------
start_native_ollama_linux() {
  if ! have ollama; then
    [ "$NO_OLLAMA_INSTALL" = "1" ] && die "Ollama is not installed. Install it and re-run."
    info "Installing native Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  if have systemctl; then
    info "Allowing Docker to reach native Ollama on 11434..."
    sudo mkdir -p /etc/systemd/system/ollama.service.d
    printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/vira-docker.conf >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now ollama >/dev/null 2>&1 || sudo systemctl restart ollama
  else
    OLLAMA_HOST=0.0.0.0:11434 nohup ollama serve >"$INSTALL_DIR/ollama.log" 2>&1 &
  fi
}

start_native_ollama_macos() {
  if ! have ollama; then
    [ "$NO_OLLAMA_INSTALL" = "1" ] && die "Ollama is not installed. Install it and re-run."
    if have brew; then
      info "Installing native Ollama with Homebrew..."
      brew install ollama
    else
      info "Installing native Ollama..."
      curl -fsSL https://ollama.com/install.sh | sh
    fi
  fi
  launchctl setenv OLLAMA_HOST "0.0.0.0:11434" >/dev/null 2>&1 || true
  if have brew && brew services list 2>/dev/null | grep -q '^ollama'; then
    brew services restart ollama >/dev/null 2>&1 || true
  else
    OLLAMA_HOST=0.0.0.0:11434 nohup ollama serve >"$INSTALL_DIR/ollama.log" 2>&1 &
  fi
  info "Waiting for native Ollama..."
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  warn "Ollama did not respond yet. Check $INSTALL_DIR/ollama.log or start the Ollama app."
}

if [ "$MODE" = "host" ]; then
  if [ "$OS_FAMILY" = "macos" ]; then start_native_ollama_macos; else start_native_ollama_linux; fi
  OLLAMA_URL="${OLLAMA_URL:-http://host.docker.internal:11434}"
fi

# ---------------------------------------------------------------------------
# Configure and start
# ---------------------------------------------------------------------------
cd "$INSTALL_DIR"

if [ -f .env ]; then
  info "Keeping existing .env"
else
  cat > .env <<EOF
VIRA_BIND_ADDRESS=${BIND_ADDRESS}
VIRA_PORT=${PORT}
VIRA_OLLAMA_MODEL=${MODEL}
EOF
  if [ -n "$OLLAMA_URL" ]; then
    printf 'VIRA_OLLAMA_URL=%s\n' "$OLLAMA_URL" >> .env
  fi
  ok "Wrote .env"
fi

COMPOSE_FILES=()
if [ "$MODE" = "bundled" ]; then
  COMPOSE_FILES=(-f compose.yaml)
  if [ "$GPU_OVERRIDE" = "1" ]; then
    COMPOSE_FILES+=(-f compose.gpu.yaml)
    ok "NVIDIA GPU detected; enabling bundled Ollama GPU override"
  fi
else
  COMPOSE_FILES=(-f compose.host-ollama.yaml)
fi

export VIRA_OLLAMA_MODEL="$MODEL"
if [ -n "$OLLAMA_URL" ]; then export VIRA_OLLAMA_URL="$OLLAMA_URL"; fi

info "Building and starting VIRA Server + worker..."
compose "${COMPOSE_FILES[@]}" up -d --build

info "Waiting for the server..."
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:${PORT}/livez" >/dev/null 2>&1; then break; fi
  sleep 2
done
if ! curl -fsS "http://127.0.0.1:${PORT}/livez" >/dev/null 2>&1; then
  warn "Server did not become healthy. Check:"
  say "  cd $INSTALL_DIR && ${DOCKER[*]} compose ${COMPOSE_FILES[*]} logs --tail=120 vira"
  exit 1
fi
ok "VIRA Server is healthy"

if [ "$NO_MODEL" != "1" ]; then
  info "Pulling model $MODEL (this can take a while)..."
  if [ "$MODE" = "bundled" ]; then
    if ! compose "${COMPOSE_FILES[@]}" --profile setup run --rm model-pull; then
      warn "Could not pull $MODEL automatically. Pull it manually:"
      say "  cd $INSTALL_DIR && ${DOCKER[*]} compose ${COMPOSE_FILES[*]} exec ollama ollama pull $MODEL"
    fi
  elif [ "$MODE" = "host" ]; then
    if ! ollama pull "$MODEL"; then
      warn "Could not pull $MODEL. Run: ollama pull $MODEL"
    fi
  else
    info "Remote Ollama models must be pulled on the remote host."
  fi
fi

say ""
ok "VIRA Server is ready."
say ""
say "  ${B}Web console${RESET}  http://localhost:${PORT}"
say "  ${B}Install dir${RESET}  ${INSTALL_DIR}"
say "  ${B}Logs${RESET}         cd $INSTALL_DIR && ${DOCKER[*]} compose ${COMPOSE_FILES[*]} logs -f vira worker"
say "  ${B}Stop${RESET}         cd $INSTALL_DIR && ${DOCKER[*]} compose ${COMPOSE_FILES[*]} down"
say ""
say "Next: open the web console and create the admin account."
say "Then install VIRA Link on each device and use http://<server-LAN-IP>:${PORT} as its server URL."
if [ "$OS_FAMILY" = "linux" ] && [ "$(id -u)" -ne 0 ] && ! docker info >/dev/null 2>&1; then
  say ""
  warn "Docker was used with sudo. Log out and back in (or run 'newgrp docker') to use Docker without sudo."
fi
