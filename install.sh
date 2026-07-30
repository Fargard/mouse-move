#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

create_config() {
  if [ -f config.json ]; then
    return
  fi

  echo "Creating config.json..."
  cat > config.json <<'JSON'
{
  "version": 1,
  "runtime": {
    "idle_seconds": 120,
    "poll_interval_seconds": 1
  },
  "activity": {
    "window_seconds": 600,
    "min_percent": 1,
    "max_percent": 40
  },
  "mouse": {
    "enabled": true,
    "min_move_duration_seconds": 0.8,
    "max_move_duration_seconds": 8,
    "wobble_pixels": 35,
    "cancel_check_interval_seconds": 0.05
  },
  "spaces": {
    "enabled": true,
    "switch_chance_percent": 35,
    "switch_step_seconds": 0.8,
    "same_display_only": true,
    "monitors": {
      "*": {
        "weights": {
          "app": 3,
          "browser": 2,
          "mixed": 2,
          "empty": 1,
          "unknown": 1
        },
        "app_kinds": {},
        "browser_apps": [
          "Arc",
          "Brave Browser",
          "Firefox",
          "Google Chrome",
          "Microsoft Edge",
          "Safari",
          "Yandex",
          "Yandex Browser"
        ],
        "mixed_kind": "mixed",
        "empty_kind": "empty"
      }
    }
  },
  "debug": {
    "window_seconds": 10,
    "min_percent": 20,
    "max_percent": 40,
    "space_switch_chance_percent": 100
  },
  "updates": {
    "check_on_start": true,
    "strategy": "github_release",
    "remote": "origin",
    "branch": "",
    "timeout_seconds": 3
  }
}
JSON
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
