#!/usr/bin/env bash
#
# run-local.sh — bootstrap + run the Idea Board platform locally in Docker.
#
# It will (on a fresh machine):
#   1. check for Docker + Docker Compose, and install Docker if missing
#   2. make sure the Docker daemon is running
#   3. build and start the full stack (Postgres + backend + frontend)
#   4. wait for health and run a quick smoke test against the API
#   5. optionally run the Python test suite and/or the agent self-heal demo
#
# Usage:
#   ./run-local.sh              # check prereqs, install Docker if needed, run the stack
#   ./run-local.sh -y           # same, but don't prompt before installing
#   ./run-local.sh --check      # only check prerequisites and report (no install, no run)
#   ./run-local.sh --no-install # run, but never auto-install (fail with instructions instead)
#   ./run-local.sh --tests      # also run the pytest suite (creates a venv)
#   ./run-local.sh --demo       # also run the agent demo (no cloud / API key needed)
#   ./run-local.sh --rebuild    # force a clean image rebuild
#   ./run-local.sh --down       # stop and remove the local stack
#   ./run-local.sh -h           # help
#
set -euo pipefail

# --------------------------------------------------------------------------- #
BACKEND_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:3000"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ASSUME_YES=0; DO_INSTALL=1; RUN_TESTS=0; RUN_DEMO=0; CHECK_ONLY=0; DO_DOWN=0; REBUILD=0

# --------------------------------------------------------------------------- #
# pretty output
if [ -t 1 ]; then
  R=$'\e[31m'; G=$'\e[32m'; Y=$'\e[33m'; B=$'\e[34m'; BOLD=$'\e[1m'; N=$'\e[0m'
else
  R=""; G=""; Y=""; B=""; BOLD=""; N=""
fi
info() { printf "%s\n" "${B}==>${N} $*"; }
ok()   { printf "%s\n" "${G}  ✓${N} $*"; }
warn() { printf "%s\n" "${Y}  !${N} $*"; }
err()  { printf "%s\n" "${R}  ✗${N} $*" >&2; }
die()  { err "$*"; exit 1; }

usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "$0"; exit 0; }

# --------------------------------------------------------------------------- #
# arg parsing
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes)        ASSUME_YES=1 ;;
    --check)         CHECK_ONLY=1 ;;
    --no-install)    DO_INSTALL=0 ;;
    --tests)         RUN_TESTS=1 ;;
    --demo)          RUN_DEMO=1 ;;
    --rebuild)       REBUILD=1 ;;
    --down)          DO_DOWN=1 ;;
    -h|--help)       usage ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

have() { command -v "$1" >/dev/null 2>&1; }

confirm() { # confirm "message" -> 0/1
  [ "$ASSUME_YES" -eq 1 ] && return 0
  printf "%s [y/N] " "$1"
  read -r reply < /dev/tty 2>/dev/null || reply=""
  case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

OS="$(uname -s)"
SUDO=""
need_sudo() {
  if [ "$(id -u)" -ne 0 ]; then
    have sudo || die "This step needs root privileges but 'sudo' was not found."
    SUDO="sudo"
  fi
}

# --------------------------------------------------------------------------- #
# docker helpers (transparently use sudo if the daemon needs it)
DOCKER_SUDO=""
docker_ok() { $DOCKER_SUDO docker info >/dev/null 2>&1; }

detect_docker_sudo() {
  if docker info >/dev/null 2>&1; then DOCKER_SUDO=""; return 0; fi
  if have sudo && sudo docker info >/dev/null 2>&1; then DOCKER_SUDO="sudo"; return 0; fi
  return 1
}

COMPOSE_BIN=""
detect_compose() {
  if $DOCKER_SUDO docker compose version >/dev/null 2>&1; then COMPOSE_BIN="docker compose"; return 0; fi
  if have docker-compose && $DOCKER_SUDO docker-compose version >/dev/null 2>&1; then COMPOSE_BIN="docker-compose"; return 0; fi
  return 1
}
compose() { $DOCKER_SUDO $COMPOSE_BIN "$@"; }

install_curl_if_missing() {
  have curl && return 0
  info "Installing curl..."
  need_sudo
  if   have apt-get; then $SUDO apt-get update -y && $SUDO apt-get install -y curl
  elif have dnf;     then $SUDO dnf install -y curl
  elif have yum;     then $SUDO yum install -y curl
  elif have pacman;  then $SUDO pacman -Sy --noconfirm curl
  elif have brew;    then brew install curl
  else die "Could not install curl automatically; please install it and re-run."
  fi
}

install_docker() {
  if [ "$DO_INSTALL" -eq 0 ]; then
    die "Docker is not installed and --no-install was set. Install Docker and re-run."
  fi
  case "$OS" in
    Linux)
      confirm "Docker is not installed. Install it now via the official get.docker.com script?" \
        || die "Docker is required. Aborting."
      install_curl_if_missing
      need_sudo
      info "Installing Docker (this can take a minute)..."
      curl -fsSL https://get.docker.com | $SUDO sh
      if have systemctl; then $SUDO systemctl enable --now docker || true; fi
      # let the current user run docker without sudo on next login
      if have usermod && [ "$(id -u)" -ne 0 ]; then
        $SUDO usermod -aG docker "$USER" || true
        warn "Added you to the 'docker' group. A re-login is needed for that to take effect;"
        warn "for this run the script will use 'sudo docker' automatically."
      fi
      ;;
    Darwin)
      if have brew; then
        confirm "Install Docker Desktop via Homebrew?" || die "Docker is required. Aborting."
        brew install --cask docker
        warn "Docker Desktop installed. Launching it now — please complete any first-run prompts."
        open -a Docker || true
      else
        die "Please install Docker Desktop from https://www.docker.com/products/docker-desktop and re-run."
      fi
      ;;
    *)
      die "Unsupported OS '$OS'. Please install Docker manually and re-run."
      ;;
  esac
}

start_daemon() {
  info "Docker daemon is not responding; trying to start it..."
  case "$OS" in
    Linux)  have systemctl && need_sudo && $SUDO systemctl start docker || true ;;
    Darwin) open -a Docker >/dev/null 2>&1 || true ;;
  esac
  for _ in $(seq 1 30); do
    detect_docker_sudo && { ok "Docker daemon is running."; return 0; }
    sleep 2
  done
  return 1
}

# --------------------------------------------------------------------------- #
ensure_docker() {
  if ! have docker; then
    warn "Docker not found."
    install_docker
    have docker || die "Docker still not available after install."
  fi
  if ! detect_docker_sudo; then
    start_daemon || die "Could not start the Docker daemon. Start Docker and re-run."
  fi
  ok "Docker is available ${DOCKER_SUDO:+(using sudo)}."
  detect_compose || die "Docker Compose not found. Install the Compose plugin ('docker compose') and re-run."
  ok "Docker Compose is available ($COMPOSE_BIN)."
}

report_check() {
  info "Prerequisite check"
  if have docker; then ok "docker: $(docker --version 2>/dev/null | head -1)"; else err "docker: NOT installed"; fi
  if detect_docker_sudo; then ok "docker daemon: running ${DOCKER_SUDO:+(needs sudo)}"; else warn "docker daemon: not responding"; fi
  if detect_compose; then ok "compose: $COMPOSE_BIN"; else warn "compose: not found"; fi
  if have python3; then ok "python3: $(python3 --version 2>&1)"; else warn "python3: not found (only needed for --tests/--demo)"; fi
  if have curl; then ok "curl: present"; else warn "curl: not found (used for smoke tests)"; fi
}

# --------------------------------------------------------------------------- #
wait_for() { # url name tries
  local url="$1" name="$2" tries="${3:-40}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then ok "$name reachable"; return 0; fi
    sleep 2
  done
  return 1
}

smoke_test() {
  info "Smoke-testing the API"
  local health
  health="$(curl -fsS "$BACKEND_URL/api/health")" || die "health endpoint failed"
  ok "GET /api/health -> $health"
  local created
  created="$(curl -fsS -X POST "$BACKEND_URL/api/ideas" \
    -H 'Content-Type: application/json' \
    -d '{"content":"my first local idea"}')" || die "create idea failed"
  ok "POST /api/ideas -> $created"
  local list
  list="$(curl -fsS "$BACKEND_URL/api/ideas")" || die "list ideas failed"
  ok "GET /api/ideas -> $list"
  if curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then ok "frontend serving at $FRONTEND_URL"; else warn "frontend not reachable yet"; fi
}

run_tests() {
  info "Running the Python test suite"
  have python3 || die "python3 is required for --tests"
  python3 -m venv .venv-local
  # shellcheck disable=SC1091
  . .venv-local/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements-dev.txt
  pytest -q
  deactivate
  ok "test suite passed"
}

run_demo() {
  info "Running the agent self-heal demo (no cloud / API key needed)"
  have python3 || die "python3 is required for --demo"
  python3 -m ai.agent demo
}

# --------------------------------------------------------------------------- #
main() {
  printf "%s\n" "${BOLD}Idea Board — local bootstrap${N}"

  if [ "$CHECK_ONLY" -eq 1 ]; then
    report_check
    exit 0
  fi

  ensure_docker

  if [ "$DO_DOWN" -eq 1 ]; then
    info "Stopping the local stack"
    compose down -v
    ok "stopped and cleaned up"
    exit 0
  fi

  install_curl_if_missing

  info "Building and starting the stack (Postgres + backend + frontend)"
  if [ "$REBUILD" -eq 1 ]; then
    compose build --no-cache
  fi
  compose up -d --build

  wait_for "$BACKEND_URL/api/health" "backend" 45 \
    || { err "backend did not become healthy in time; showing recent logs:"; compose logs --tail 40 backend; exit 1; }

  smoke_test

  [ "$RUN_TESTS" -eq 1 ] && run_tests
  [ "$RUN_DEMO" -eq 1 ] && run_demo

  printf "\n%s\n" "${G}${BOLD}Local stack is up.${N}"
  printf "  Frontend : %s\n" "$FRONTEND_URL"
  printf "  API      : %s/api/health\n" "$BACKEND_URL"
  printf "  Logs     : %s logs -f\n" "$COMPOSE_BIN"
  printf "  Stop     : ./run-local.sh --down\n"
  printf "\nOnce this looks good locally, deploy to a cloud with the CI workflow (see README).\n"
}

main
