# Activity

Small macOS utility that keeps the machine active without interrupting you.

When you are using the computer, the script stays paused. After a configured
idle period it starts doing light activity:

- moves the mouse across the available screen;
- occasionally switches macOS Spaces;
- stops again as soon as you interact with the machine.

Normal mode is quiet: it prints start, stop, and config reload messages.

## Install

Requirements:

- macOS
- Python 3
- Homebrew

Run:

```sh
./install.sh
```

The installer creates a local `config.json` on the first run. The file is
ignored by Git and is never overwritten on later installs.

Then grant permissions in System Settings:

- Privacy & Security -> Accessibility: your terminal app
- Privacy & Security -> Input Monitoring: your terminal app
- Privacy & Security -> Accessibility: `yabai`

Start or restart the Space service after granting permissions:

```sh
yabai --restart-service
```

## Run

The CLI is intentionally small. Runtime tuning lives in `config.json`; command
line flags only choose the run mode.

Default mode uses `mouse.enabled` and `spaces.enabled` from `config.json`.
The generated config enables both:

```sh
python3 bot.py
```

Run only one mode:

```sh
python3 bot.py --mouse-move
python3 bot.py --switch-spaces
```

Run both explicitly:

```sh
python3 bot.py --mouse-move --switch-spaces
```

Run debug mode:

```sh
python3 bot.py --debug
```

Debug mode uses shorter activity windows from `config.json` and prints extra
logs so you can see behavior without waiting for long intervals.

Stop with `Ctrl-C`.

## Config

`config.example.json` is the default example stored in the repository.
`config.json` is your local configuration file. It is created by `install.sh`
only when missing and ignored by Git, so each user can keep their own settings.

The running script watches this file and reloads it automatically after you
save changes. Successful reloads, changed settings, and reload errors are
always printed to the terminal. If the file is temporarily invalid, the script
keeps using the last valid config and tries again after the next save.

Top-level sections:

- `runtime`: when the script considers you idle and how often it checks state
- `activity`: how activity is spread across each accounting window
- `mouse`: mouse movement shape and duration
- `spaces`: Space switching frequency, animation timing, and Space weights
- `debug`: faster values used only with `--debug`
- `updates`: optional startup check for newer code in Git
- `logging`: local log file and rotation settings

See `config.example.json` for the complete default config.

## Activity Settings

`activity.window_seconds` is the accounting window. With `600`, the script
plans activity inside 10-minute chunks.

`activity.min_percent` and `activity.max_percent` define the random activity
range inside each window. For example, in a 10-minute window:

- `1` means at least 6 seconds of total activity;
- `40` means up to 4 minutes of total activity.

`runtime.idle_seconds` controls how long you must be inactive before the script
resumes. The default is `120` seconds.

`mouse.enabled` and `spaces.enabled` control the default run mode. If you run
`python3 bot.py` without mode flags, these values decide what starts. CLI flags
like `--mouse-move` and `--switch-spaces` override them only for that run.

## Mouse Settings

`mouse.enabled` enables mouse movement in the default run mode.

`mouse.min_move_duration_seconds` and `mouse.max_move_duration_seconds` control
how long one mouse movement can take.

`mouse.wobble_pixels` controls how much the path can drift away from a straight
line. Higher values make movement less straight.

`mouse.cancel_check_interval_seconds` controls how often a running mouse
movement checks for real user input. Lower values stop sooner after input, but
produce more movement steps.

## Space Settings

`spaces.enabled` enables Space switching in the default run mode.

`spaces.switch_chance_percent` is the chance of one Space switch inside each
activity window. `0` disables Space switching attempts from the schedule, `100`
attempts one switch every window.

`spaces.switch_step_seconds` controls the pause between repeated
`Ctrl+Left`/`Ctrl+Right` presses when the target Space is several steps away.

`spaces.same_display_only` keeps Space switching on the currently focused
display. Set it to `false` to allow targets from other displays too.

`spaces.monitors` is monitor-aware:

```json
{
  "monitors": {
    "*": {
      "weights": {
        "app": 3,
        "browser": 2,
        "mixed": 2,
        "empty": 1,
        "unknown": 1
      }
    },
    "2": {
      "weights": {
        "browser": 5,
        "app": 1,
        "mixed": 1
      }
    }
  }
}
```

`"*"` is the default profile for every monitor. Add `"1"`, `"2"`, or another
display number from `yabai` when a monitor needs its own weights.

Weights are relative. A kind with weight `8` is selected more often than a kind
with weight `1`.

`app_kinds` maps application names reported by `yabai` to custom kinds:

```json
{
  "app_kinds": {
    "Visual Studio Code": "vscode",
    "iTerm2": "iterm",
    "Slack": "slack"
  },
  "weights": {
    "vscode": 8,
    "iterm": 2,
    "slack": 1,
    "app": 2,
    "mixed": 2,
    "empty": 1
  }
}
```

Built-in generic kinds:

- `app`: one non-browser app
- `browser`: one browser app
- `mixed`: multiple apps/windows
- `empty`: no visible windows
- `unknown`: fallback kind

If you use `yabai` labels, a label can also be used as a kind as long as it is
present in `weights`.

## Update Checks

`updates.check_on_start` controls whether the script checks for a newer version
when it starts.

The check is read-only. It prints a message if a newer version exists, but it
does not run `git pull` or change any files.

`updates.strategy` controls what "newer" means:

- `github_release`: compares the local version tag with the latest GitHub
  release from `gh release list`
- `git_remote_branch`: compares local `HEAD` with a remote Git branch

`github_release` needs GitHub CLI (`gh`) and is the default strategy.

`updates.remote` is usually `origin`. For `github_release`, the script uses it
to discover the GitHub repository. For `git_remote_branch`, `updates.branch`
can be left empty to use the current branch, or set to a specific branch name.
`updates.timeout_seconds` keeps startup from waiting too long if the network is
slow.

## Logging

`logging.enabled` controls whether runtime warnings are written to a local log
file. Console output stays short and includes a timestamp plus the log file
path, while the log file keeps detailed diagnostics.

By default, logs are written to `logs/activity.log`. The installer creates the
`logs/` directory, and the running script recreates it if needed. The `logs/`
directory is ignored by Git.

`logging.max_bytes` controls when the current log file is rotated.
`logging.backup_count` controls how many rotated log files are kept. Rotated
files use the standard numeric suffix format: `activity.log.1`,
`activity.log.2`, and so on.

## Behavior

Mouse movement uses random points across the available screen and a slightly
wobbly path instead of a perfectly straight line.

Space switching uses `yabai` to detect the currently available Spaces and the
apps inside them. The actual switch is performed with `Ctrl+Left` and
`Ctrl+Right`, so the macOS transition stays animated.

If real keyboard, mouse, or trackpad input appears while the script is moving
the mouse or stepping through Spaces, the current action is interrupted and the
script pauses.
