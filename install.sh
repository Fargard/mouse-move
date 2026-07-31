#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

create_config() {
  if [ -f config.json ]; then
    return
  fi

  if [ ! -f config.example.json ]; then
    echo "config.example.json is missing."
    exit 1
  fi

  echo "Creating config.json..."
  cp config.example.json config.json
}

create_logs_dir() {
  if [ ! -d logs ]; then
    echo "Creating logs directory..."
    mkdir -p logs
  fi
}

explain_brew_failure() {
  log_file="$1"

  echo
  echo "Homebrew could not install yabai."

  if grep -qi "Command Line Tools are too outdated" "$log_file"; then
    echo "Homebrew reports an Xcode Command Line Tools problem."
    echo "Check what Homebrew sees with:"
    echo "  brew config"
    echo "Then update Xcode/Command Line Tools and rerun this installer."
  else
    echo "Run this for details:"
    echo "  brew doctor"
  fi
}

echo "Installing Python dependencies..."
python3 -m pip install -r requirements.txt
create_config
create_logs_dir

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required to install yabai."
  echo "Install it from https://brew.sh/ and run this script again."
  exit 1
fi

echo "Installing macOS dependencies..."
brew_log="$(mktemp -t activity-brew-install.XXXXXX)"
if [ -f Brewfile ]; then
  if ! brew bundle >"$brew_log" 2>&1; then
    cat "$brew_log"
    explain_brew_failure "$brew_log"
    exit 1
  fi
else
  if ! brew install koekeishiya/formulae/yabai >"$brew_log" 2>&1; then
    cat "$brew_log"
    explain_brew_failure "$brew_log"
    exit 1
  fi
fi
cat "$brew_log"

if command -v yabai >/dev/null 2>&1; then
  echo "Starting yabai service..."
  if ! yabai --start-service; then
    echo "Could not start yabai yet."
    echo "Grant yabai Accessibility permission in System Settings, then run:"
    echo "  yabai --restart-service"
  fi
fi

echo "Done."
