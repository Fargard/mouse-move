import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import threading
import time

import pyautogui
import Quartz


DEFAULT_IDLE_SECONDS = 120
DEFAULT_WINDOW_SECONDS = 600
DEFAULT_MIN_ACTIVITY_PERCENT = 1
DEFAULT_MAX_ACTIVITY_PERCENT = 40
DEFAULT_MIN_MOVE_DURATION_SECONDS = 0.8
DEFAULT_MAX_MOVE_DURATION_SECONDS = 8
DEFAULT_WOBBLE_PIXELS = 35
DEFAULT_MOUSE_CANCEL_CHECK_INTERVAL_SECONDS = 0.05
DEFAULT_SPACE_SWITCH_CHANCE_PERCENT = 35
DEFAULT_MOUSE_ENABLED = True
DEFAULT_SPACES_ENABLED = True
DEFAULT_SAME_DISPLAY_ONLY = True
DEFAULT_UPDATE_CHECK_ON_START = True
DEFAULT_UPDATE_STRATEGY = "github_release"
DEFAULT_UPDATE_REMOTE = "origin"
DEFAULT_UPDATE_BRANCH = ""
DEFAULT_UPDATE_TIMEOUT_SECONDS = 3
UPDATE_STRATEGIES = {"github_release", "git_remote_branch"}
CONFIG_PATH = "config.json"
POLL_INTERVAL_SECONDS = 1
SPACE_SWITCH_STEP_SECONDS = 0.8

INPUT_EVENT_TYPES = [
    Quartz.kCGEventLeftMouseDown,
    Quartz.kCGEventLeftMouseUp,
    Quartz.kCGEventRightMouseDown,
    Quartz.kCGEventRightMouseUp,
    Quartz.kCGEventMouseMoved,
    Quartz.kCGEventLeftMouseDragged,
    Quartz.kCGEventRightMouseDragged,
    Quartz.kCGEventKeyDown,
    Quartz.kCGEventKeyUp,
    Quartz.kCGEventFlagsChanged,
    Quartz.kCGEventScrollWheel,
    Quartz.kCGEventOtherMouseDown,
    Quartz.kCGEventOtherMouseUp,
    Quartz.kCGEventOtherMouseDragged,
]


class UserInputMonitor:
    def __init__(self, initial_idle_seconds=0):
        self.own_pid = os.getpid()
        self.last_user_input_at = time.monotonic() - initial_idle_seconds
        self.lock = threading.Lock()
        self.started = threading.Event()
        self.error = None
        self.event_tap = None
        self.callback = self.handle_event

    def start(self):
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        self.started.wait(timeout=3)

        if self.error:
            raise RuntimeError(self.error)
        if not self.event_tap:
            raise RuntimeError("Could not start macOS input monitor.")

    def idle_seconds(self):
        with self.lock:
            return time.monotonic() - self.last_user_input_at

    def handle_event(self, proxy, event_type, event, refcon):
        if event_type in (
            Quartz.kCGEventTapDisabledByTimeout,
            Quartz.kCGEventTapDisabledByUserInput,
        ):
            Quartz.CGEventTapEnable(self.event_tap, True)
            return event

        source_pid = Quartz.CGEventGetIntegerValueField(
            event,
            Quartz.kCGEventSourceUnixProcessID,
        )
        if source_pid != self.own_pid:
            with self.lock:
                self.last_user_input_at = time.monotonic()

        return event

    def run(self):
        event_mask = 0
        for event_type in INPUT_EVENT_TYPES:
            event_mask |= Quartz.CGEventMaskBit(event_type)

        self.event_tap = Quartz.CGEventTapCreate(
            Quartz.kCGHIDEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            event_mask,
            self.callback,
            None,
        )

        if not self.event_tap:
            self.error = (
                "Could not create macOS input monitor. Grant Accessibility and "
                "Input Monitoring permissions to your terminal app."
            )
            self.started.set()
            return

        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, self.event_tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            run_loop_source,
            Quartz.kCFRunLoopCommonModes,
        )
        Quartz.CGEventTapEnable(self.event_tap, True)
        self.started.set()
        Quartz.CFRunLoopRun()


@dataclass
class ScheduledMove:
    start_at: float
    duration: float


class ActivityWindow:
    def __init__(
        self,
        window_seconds,
        min_activity_percent,
        max_activity_percent,
        min_move_duration_seconds,
        max_move_duration_seconds,
    ):
        self.window_seconds = window_seconds
        self.min_activity_percent = min_activity_percent
        self.max_activity_percent = max_activity_percent
        self.min_move_duration_seconds = min_move_duration_seconds
        self.max_move_duration_seconds = max_move_duration_seconds
        self.started_at = 0
        self.moves = []
        self.next_move_index = 0

    def start(self, now):
        self.started_at = now
        self.next_move_index = 0
        activity_percent = random.uniform(
            self.min_activity_percent,
            self.max_activity_percent,
        )
        active_seconds = self.window_seconds * activity_percent / 100
        self.moves = self.build_moves(now, active_seconds)

    def has_ended(self, now):
        return now - self.started_at >= self.window_seconds

    def next_due_move(self, now):
        if self.next_move_index >= len(self.moves):
            return None

        scheduled_move = self.moves[self.next_move_index]
        if scheduled_move.start_at > now:
            return None

        self.next_move_index += 1
        return scheduled_move

    def build_moves(self, now, active_seconds):
        durations = []
        remaining = active_seconds

        while remaining > 0:
            if remaining <= self.max_move_duration_seconds:
                duration = remaining
            else:
                duration = random.uniform(
                    self.min_move_duration_seconds,
                    min(self.max_move_duration_seconds, remaining),
                )
            durations.append(duration)
            remaining -= duration

        if not durations:
            durations.append(self.min_move_duration_seconds)

        total_move_time = sum(durations)
        total_gap_time = max(0, self.window_seconds - total_move_time)
        gap_weights = [random.random() for _ in range(len(durations) + 1)]
        total_weight = sum(gap_weights) or 1
        gaps = [total_gap_time * weight / total_weight for weight in gap_weights]

        moves = []
        cursor = now + gaps[0]
        for index, duration in enumerate(durations):
            moves.append(ScheduledMove(start_at=cursor, duration=duration))
            cursor += duration + gaps[index + 1]

        return moves


@dataclass
class ScreenRect:
    x: int
    y: int
    width: int
    height: int

    @property
    def area(self):
        return self.width * self.height

    @property
    def max_x(self):
        return self.x + self.width - 1

    @property
    def max_y(self):
        return self.y + self.height - 1


@dataclass
class YabaiSpace:
    index: int
    display: int
    kind: str
    weight: float
    focused: bool


@dataclass
class RuntimeConfig:
    idle_seconds: float
    poll_interval_seconds: float


@dataclass
class ActivityConfig:
    window_seconds: float
    min_percent: float
    max_percent: float


@dataclass
class MouseConfig:
    enabled: bool
    min_move_duration_seconds: float
    max_move_duration_seconds: float
    wobble_pixels: int
    cancel_check_interval_seconds: float


@dataclass
class SpacesRuntimeConfig:
    enabled: bool
    switch_chance_percent: float
    switch_step_seconds: float
    same_display_only: bool
    config: "SpaceConfig"


@dataclass
class DebugConfig:
    activity: ActivityConfig
    space_switch_chance_percent: float


@dataclass
class UpdateConfig:
    check_on_start: bool
    strategy: str
    remote: str
    branch: str
    timeout_seconds: float


@dataclass
class AppConfig:
    runtime: RuntimeConfig
    activity: ActivityConfig
    mouse: MouseConfig
    spaces: SpacesRuntimeConfig
    debug: DebugConfig
    updates: UpdateConfig


@dataclass
class LoadedConfig:
    config: AppConfig
    modified_at: int


@dataclass
class RuntimeModes:
    mouse_move: bool
    switch_spaces: bool


class SpaceConfig:
    def __init__(self, config):
        monitors = config.get("monitors")
        if not isinstance(monitors, dict) or "*" not in monitors:
            raise ValueError("spaces.monitors must contain *")

        for profile in monitors.values():
            self.normalize_profile(profile)

        self.monitors = {
            str(display): profile
            for display, profile in monitors.items()
        }

    def profile_for_display(self, display):
        profile = dict(self.monitors["*"])
        profile.update(self.monitors.get(str(display), {}))
        return self.normalize_profile(profile)

    def normalize_profile(self, profile):
        if not isinstance(profile, dict):
            raise ValueError("Each spaces monitor profile must be an object.")

        weights = profile.get("weights", {})
        if not isinstance(weights, dict):
            raise ValueError("Monitor weights must be an object.")

        app_kinds = profile.get("app_kinds", {})
        if not isinstance(app_kinds, dict):
            raise ValueError("Monitor app_kinds must be an object.")

        browser_apps = profile.get("browser_apps", [])
        if not isinstance(browser_apps, list):
            raise ValueError("Monitor browser_apps must be a list.")

        normalized_weights = {}
        for kind, weight in weights.items():
            parsed_weight = float(weight)
            if parsed_weight <= 0:
                raise ValueError("Space weights must be greater than 0.")
            normalized_weights[str(kind).strip().lower()] = parsed_weight

        return {
            "weights": normalized_weights,
            "app_kinds": {
                str(app).strip().lower(): str(kind).strip().lower()
                for app, kind in app_kinds.items()
                if str(app).strip() and str(kind).strip()
            },
            "browser_apps": {
                str(app).strip().lower()
                for app in browser_apps
                if str(app).strip()
            },
            "mixed_kind": str(profile.get("mixed_kind", "mixed")).strip().lower(),
            "empty_kind": str(profile.get("empty_kind", "empty")).strip().lower(),
        }


class SpaceSwitcher:
    def __init__(
        self,
        config,
        switch_chance,
        switch_step_seconds,
        same_display_only,
    ):
        self.config = config
        self.switch_chance = switch_chance
        self.switch_step_seconds = switch_step_seconds
        self.same_display_only = same_display_only
        self.next_switch_at = None
        self.switched_in_window = False

    def start_window(self, now, window_seconds):
        self.switched_in_window = False
        self.next_switch_at = None

        if random.random() > self.switch_chance:
            return
        spaces = self.query_weighted_spaces()
        current, choices = self.switch_choices(spaces)
        if not current or not choices:
            return

        self.next_switch_at = now + random.uniform(0, window_seconds)

    def reset_window(self):
        self.next_switch_at = None
        self.switched_in_window = False

    def switch_if_due(self, now, should_stop):
        if self.next_switch_at is None:
            return True
        if self.switched_in_window or now < self.next_switch_at:
            return True
        if should_stop():
            return False

        spaces = self.query_weighted_spaces()
        current, choices = self.switch_choices(spaces)
        if not current or not choices:
            self.switched_in_window = True
            return True

        target = random.choices(
            choices,
            weights=[space.weight for space in choices],
            k=1,
        )[0]
        switched = switch_space_by_steps(
            target.index - current.index,
            self.switch_step_seconds,
            should_stop,
        )
        if not switched:
            return False

        self.switched_in_window = True
        self.next_switch_at = None
        return True

    def switch_choices(self, spaces):
        current = next((space for space in spaces if space.focused), None)
        choices = [space for space in spaces if not space.focused]
        if current and self.same_display_only:
            choices = [
                space
                for space in choices
                if space.display == current.display
            ]
        return current, choices

    def query_weighted_spaces(self):
        spaces = self.query_json("query", "--spaces")
        windows = self.query_json("query", "--windows")
        windows_by_space = self.group_windows_by_space(windows)
        weighted_spaces = []

        for space in spaces:
            index = int(space["index"])
            display = int(space.get("display", 1))
            profile = self.config.profile_for_display(display)
            kind = self.classify_space(space, windows_by_space.get(index, []), profile)
            weight = profile["weights"].get(kind)
            if weight is None:
                continue

            weighted_spaces.append(YabaiSpace(
                index=index,
                display=display,
                kind=kind,
                weight=weight,
                focused=self.is_focused(space),
            ))

        return weighted_spaces

    def classify_space(self, space, windows, profile):
        weights = profile["weights"]
        label = str(space.get("label") or "").strip().lower()
        if label in weights:
            return label

        app_names = {
            str(window.get("app") or "").strip().lower()
            for window in windows
            if str(window.get("app") or "").strip()
        }

        if not app_names:
            empty_kind = profile["empty_kind"]
            return empty_kind if empty_kind in weights else "empty"
        if len(app_names) == 1:
            app_name = next(iter(app_names))
            if app_name in profile["browser_apps"]:
                return "browser"
            if app_name in profile["app_kinds"]:
                mapped_kind = profile["app_kinds"][app_name]
                if mapped_kind in weights:
                    return mapped_kind
            if app_name in weights:
                return app_name
            return "app"

        mixed_kind = profile["mixed_kind"]
        return mixed_kind if mixed_kind in weights else "mixed"

    def group_windows_by_space(self, windows):
        windows_by_space = {}
        for window in windows:
            space_index = window.get("space")
            if space_index is not None:
                windows_by_space.setdefault(int(space_index), []).append(window)
        return windows_by_space

    def is_focused(self, space):
        return bool(
            space.get("focused")
            or space.get("has-focus")
            or space.get("is-focused")
        )

    def query_json(self, *args):
        output = self.run_yabai(*args, capture_output=True)
        return json.loads(output)

    def run_yabai(self, *args, capture_output=False):
        try:
            result = subprocess.run(
                ["yabai", "-m", *args],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as error:
            raise RuntimeError(
                "yabai is not installed or not available in PATH."
            ) from error
        except subprocess.CalledProcessError as error:
            message = error.stderr.strip() or str(error)
            if "failed to connect to socket" in message:
                message = (
                    "yabai is installed, but its service is not running. "
                    "Grant yabai Accessibility permission in System Settings, "
                    "then run `yabai --restart-service`."
                )
            raise RuntimeError(f"yabai command failed: {message}") from error

        return result.stdout if capture_output else ""


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def switch_space_by_steps(delta, step_seconds, should_stop):
    direction = "right" if delta > 0 else "left"
    for _ in range(abs(delta)):
        if should_stop():
            return False
        pyautogui.hotkey("ctrl", direction)
        if not cancellable_sleep(step_seconds, should_stop):
            return False
    return True


def cancellable_sleep(duration, should_stop, interval=0.05):
    deadline = time.monotonic() + duration
    while True:
        if should_stop():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(interval, remaining))


def screen_rects():
    result, displays, _ = Quartz.CGGetActiveDisplayList(32, None, None)
    if result == 0 and displays:
        rects = []
        for display in displays:
            bounds = Quartz.CGDisplayBounds(display)
            width = round(bounds.size.width)
            height = round(bounds.size.height)
            if width > 0 and height > 0:
                rects.append(ScreenRect(
                    x=round(bounds.origin.x),
                    y=round(bounds.origin.y),
                    width=width,
                    height=height,
                ))
        if rects:
            return rects

    screen_width, screen_height = pyautogui.size()
    return [ScreenRect(0, 0, max(1, screen_width), max(1, screen_height))]


def desktop_bounds(rects):
    return (
        min(rect.x for rect in rects),
        min(rect.y for rect in rects),
        max(rect.max_x for rect in rects),
        max(rect.max_y for rect in rects),
    )


def random_screen_position():
    rects = screen_rects()
    selected_rect = random.choices(
        rects,
        weights=[rect.area for rect in rects],
        k=1,
    )[0]
    return (
        random.randint(selected_rect.x, selected_rect.max_x),
        random.randint(selected_rect.y, selected_rect.max_y),
    )


def wobbly_path(start_x, start_y, end_x, end_y, wobble_pixels):
    min_x, min_y, max_x, max_y = desktop_bounds(screen_rects())
    waypoint_count = random.randint(2, 5)
    points = []

    for index in range(1, waypoint_count + 1):
        progress = index / (waypoint_count + 1)
        base_x = start_x + (end_x - start_x) * progress
        base_y = start_y + (end_y - start_y) * progress
        wobble_x = random.randint(-wobble_pixels, wobble_pixels)
        wobble_y = random.randint(-wobble_pixels, wobble_pixels)
        points.append((
            clamp(round(base_x + wobble_x), min_x, max_x),
            clamp(round(base_y + wobble_y), min_y, max_y),
        ))

    points.append((end_x, end_y))
    return points


def ease_in_out_quad(progress):
    if progress < 0.5:
        return 2 * progress * progress
    return 1 - ((-2 * progress + 2) ** 2) / 2


def move_mouse(duration, mouse_config, should_stop):
    current_x, current_y = pyautogui.position()
    next_x, next_y = random_screen_position()
    path = wobbly_path(
        current_x,
        current_y,
        next_x,
        next_y,
        mouse_config.wobble_pixels,
    )
    segment_duration = duration / len(path)
    start_x = current_x
    start_y = current_y

    for end_x, end_y in path:
        if should_stop():
            return False

        step_count = max(
            1,
            math.ceil(
                segment_duration / mouse_config.cancel_check_interval_seconds
            ),
        )
        for step in range(1, step_count + 1):
            if should_stop():
                return False

            progress = ease_in_out_quad(step / step_count)
            x = round(start_x + (end_x - start_x) * progress)
            y = round(start_y + (end_y - start_y) * progress)
            pyautogui.moveTo(x, y)

            if not cancellable_sleep(
                segment_duration / step_count,
                should_stop,
                mouse_config.cancel_check_interval_seconds,
            ):
                return False

        start_x = end_x
        start_y = end_y

    return True


def parse_args():
    parser = argparse.ArgumentParser(
        description="Move the mouse and switch macOS Spaces after the Mac is idle.",
        add_help=False,
    )
    parser.add_argument(
        "--mouse-move",
        action="store_true",
    )
    parser.add_argument(
        "--switch-spaces",
        action="store_true",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
    )
    return parser.parse_args()


def selected_modes(args, config):
    if args.mouse_move or args.switch_spaces:
        return RuntimeModes(
            mouse_move=args.mouse_move,
            switch_spaces=args.switch_spaces,
        )

    return RuntimeModes(
        mouse_move=config.mouse.enabled,
        switch_spaces=config.spaces.enabled,
    )


def load_config():
    config_path = Path(CONFIG_PATH)
    if not config_path.exists():
        raise RuntimeError(
            f"{CONFIG_PATH} is required. Run ./install.sh to create it."
        )

    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid {CONFIG_PATH}: {error}") from error
    except OSError as error:
        raise RuntimeError(f"Could not load {CONFIG_PATH}: {error}") from error

    try:
        return parse_config(config)
    except (TypeError, ValueError, KeyError) as error:
        raise RuntimeError(f"Invalid {CONFIG_PATH}: {error}") from error


def load_config_with_mtime():
    config_path = Path(CONFIG_PATH)
    config = load_config()
    try:
        modified_at = config_path.stat().st_mtime_ns
    except OSError as error:
        raise RuntimeError(f"Could not read {CONFIG_PATH} metadata: {error}") from error
    return LoadedConfig(config=config, modified_at=modified_at)


def reload_config_if_changed(loaded_config):
    config_path = Path(CONFIG_PATH)
    try:
        modified_at = config_path.stat().st_mtime_ns
    except OSError as error:
        print(f"Config reload skipped: {error}.")
        return loaded_config, False

    if modified_at == loaded_config.modified_at:
        return loaded_config, False

    try:
        reloaded_config = load_config()
    except RuntimeError as error:
        print(f"Config reload failed. Keeping previous config. {error}")
        return LoadedConfig(loaded_config.config, modified_at), False

    print("Config reloaded.")
    for change in summarize_config_changes(loaded_config.config, reloaded_config):
        print(f"  {change}")
    return LoadedConfig(reloaded_config, modified_at), True


def summarize_config_changes(old_config, new_config):
    fields = [
        ("runtime.idle_seconds", old_config.runtime.idle_seconds, new_config.runtime.idle_seconds),
        (
            "runtime.poll_interval_seconds",
            old_config.runtime.poll_interval_seconds,
            new_config.runtime.poll_interval_seconds,
        ),
        (
            "activity.window_seconds",
            old_config.activity.window_seconds,
            new_config.activity.window_seconds,
        ),
        ("activity.min_percent", old_config.activity.min_percent, new_config.activity.min_percent),
        ("activity.max_percent", old_config.activity.max_percent, new_config.activity.max_percent),
        ("mouse.enabled", old_config.mouse.enabled, new_config.mouse.enabled),
        (
            "mouse.min_move_duration_seconds",
            old_config.mouse.min_move_duration_seconds,
            new_config.mouse.min_move_duration_seconds,
        ),
        (
            "mouse.max_move_duration_seconds",
            old_config.mouse.max_move_duration_seconds,
            new_config.mouse.max_move_duration_seconds,
        ),
        ("mouse.wobble_pixels", old_config.mouse.wobble_pixels, new_config.mouse.wobble_pixels),
        (
            "mouse.cancel_check_interval_seconds",
            old_config.mouse.cancel_check_interval_seconds,
            new_config.mouse.cancel_check_interval_seconds,
        ),
        ("spaces.enabled", old_config.spaces.enabled, new_config.spaces.enabled),
        (
            "spaces.switch_chance_percent",
            old_config.spaces.switch_chance_percent,
            new_config.spaces.switch_chance_percent,
        ),
        (
            "spaces.switch_step_seconds",
            old_config.spaces.switch_step_seconds,
            new_config.spaces.switch_step_seconds,
        ),
        (
            "spaces.same_display_only",
            old_config.spaces.same_display_only,
            new_config.spaces.same_display_only,
        ),
        (
            "debug.window_seconds",
            old_config.debug.activity.window_seconds,
            new_config.debug.activity.window_seconds,
        ),
        (
            "debug.min_percent",
            old_config.debug.activity.min_percent,
            new_config.debug.activity.min_percent,
        ),
        (
            "debug.max_percent",
            old_config.debug.activity.max_percent,
            new_config.debug.activity.max_percent,
        ),
        (
            "debug.space_switch_chance_percent",
            old_config.debug.space_switch_chance_percent,
            new_config.debug.space_switch_chance_percent,
        ),
        (
            "updates.check_on_start",
            old_config.updates.check_on_start,
            new_config.updates.check_on_start,
        ),
        ("updates.strategy", old_config.updates.strategy, new_config.updates.strategy),
        ("updates.remote", old_config.updates.remote, new_config.updates.remote),
        ("updates.branch", old_config.updates.branch, new_config.updates.branch),
        (
            "updates.timeout_seconds",
            old_config.updates.timeout_seconds,
            new_config.updates.timeout_seconds,
        ),
    ]
    changes = [
        f"{name}: {format_config_value(old_value)} -> {format_config_value(new_value)}"
        for name, old_value, new_value in fields
        if old_value != new_value
    ]

    if old_config.spaces.config.monitors != new_config.spaces.config.monitors:
        changes.append("spaces.monitors: changed")

    return changes


def format_config_value(value):
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def check_for_updates(update_config, debug):
    if not update_config.check_on_start:
        return

    if update_config.strategy == "github_release":
        check_for_release_updates(update_config, debug)
        return
    if update_config.strategy == "git_remote_branch":
        check_for_branch_updates(update_config, debug)
        return

    debug_log(debug, f"Update check skipped: unknown strategy {update_config.strategy}.")


def check_for_release_updates(update_config, debug):
    try:
        current_tag = current_version_tag(update_config.timeout_seconds)
        repo = github_repo_from_remote(
            update_config.remote,
            update_config.timeout_seconds,
        )
        latest_tag = latest_github_release_tag(repo, update_config.timeout_seconds)
    except RuntimeError as error:
        debug_log(debug, f"Update check skipped: {error}")
        return

    if not latest_tag:
        debug_log(debug, "Update check skipped: no GitHub releases found.")
        return

    if latest_tag != current_tag:
        print(
            "Update available: "
            f"GitHub release {latest_tag} is newer than local {current_tag}. "
            "Run `git pull` when convenient."
        )
    else:
        debug_log(debug, "Update check: local release is up to date.")


def check_for_branch_updates(update_config, debug):
    try:
        local_head = run_git(
            ["rev-parse", "HEAD"],
            update_config.timeout_seconds,
        )
        branch = update_config.branch or run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"],
            update_config.timeout_seconds,
        )
        if branch == "HEAD":
            debug_log(debug, "Update check skipped: detached HEAD.")
            return

        remote_head = remote_branch_head(
            update_config.remote,
            branch,
            update_config.timeout_seconds,
        )
    except RuntimeError as error:
        debug_log(debug, f"Update check skipped: {error}")
        return

    if remote_head and remote_head != local_head:
        print(
            "Update available: "
            f"{update_config.remote}/{branch} is newer than local HEAD. "
            "Run `git pull` when convenient."
        )
    else:
        debug_log(debug, "Update check: local version is up to date.")


def current_version_tag(timeout_seconds):
    try:
        return run_git(["describe", "--tags", "--exact-match", "HEAD"], timeout_seconds)
    except RuntimeError:
        pass

    try:
        return run_git(["describe", "--tags", "--abbrev=0"], timeout_seconds)
    except RuntimeError:
        return "untagged"


def github_repo_from_remote(remote, timeout_seconds):
    remote_url = run_git(["remote", "get-url", remote], timeout_seconds)
    repo = parse_github_repo(remote_url)
    if not repo:
        raise RuntimeError(f"remote {remote} is not a GitHub repository")
    return repo


def parse_github_repo(remote_url):
    clean_url = remote_url.strip()
    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    https_prefix = "https://github.com/"
    ssh_prefix = "git@github.com:"
    if clean_url.startswith(https_prefix):
        return clean_url[len(https_prefix):]
    if clean_url.startswith(ssh_prefix):
        return clean_url[len(ssh_prefix):]
    return ""


def latest_github_release_tag(repo, timeout_seconds):
    output = run_gh(
        [
            "release",
            "list",
            "--repo",
            repo,
            "--limit",
            "1",
            "--json",
            "tagName",
        ],
        timeout_seconds,
    )
    releases = json.loads(output)
    if not releases:
        return ""
    return str(releases[0].get("tagName") or "").strip()


def remote_branch_head(remote, branch, timeout_seconds):
    output = run_git(["ls-remote", remote, branch], timeout_seconds)
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith(f"/{branch}"):
            return parts[0]
        if len(parts) >= 1:
            return parts[0]
    return ""


def run_git(args, timeout_seconds):
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError("git is not installed or not available in PATH") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("git command timed out") from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or str(error)
        raise RuntimeError(message) from error

    return result.stdout.strip()


def run_gh(args, timeout_seconds):
    try:
        result = subprocess.run(
            ["gh", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "GitHub CLI is not installed or not available in PATH"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("GitHub CLI command timed out") from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or str(error)
        raise RuntimeError(message) from error

    return result.stdout.strip()


def parse_config(config):
    if not isinstance(config, dict):
        raise ValueError("root value must be an object")

    runtime = config.get("runtime", {})
    activity = config.get("activity", {})
    mouse = config.get("mouse", {})
    spaces = config.get("spaces", {})
    debug = config.get("debug", {})
    updates = config.get("updates", {})

    runtime_config = RuntimeConfig(
        idle_seconds=number_at(runtime, "idle_seconds", DEFAULT_IDLE_SECONDS),
        poll_interval_seconds=number_at(
            runtime,
            "poll_interval_seconds",
            POLL_INTERVAL_SECONDS,
        ),
    )
    activity_config = ActivityConfig(
        window_seconds=number_at(activity, "window_seconds", DEFAULT_WINDOW_SECONDS),
        min_percent=number_at(
            activity,
            "min_percent",
            DEFAULT_MIN_ACTIVITY_PERCENT,
        ),
        max_percent=number_at(
            activity,
            "max_percent",
            DEFAULT_MAX_ACTIVITY_PERCENT,
        ),
    )
    mouse_config = MouseConfig(
        enabled=bool_at(mouse, "enabled", DEFAULT_MOUSE_ENABLED),
        min_move_duration_seconds=number_at(
            mouse,
            "min_move_duration_seconds",
            DEFAULT_MIN_MOVE_DURATION_SECONDS,
        ),
        max_move_duration_seconds=number_at(
            mouse,
            "max_move_duration_seconds",
            DEFAULT_MAX_MOVE_DURATION_SECONDS,
        ),
        wobble_pixels=integer_at(mouse, "wobble_pixels", DEFAULT_WOBBLE_PIXELS),
        cancel_check_interval_seconds=number_at(
            mouse,
            "cancel_check_interval_seconds",
            DEFAULT_MOUSE_CANCEL_CHECK_INTERVAL_SECONDS,
        ),
    )
    spaces_config = SpacesRuntimeConfig(
        enabled=bool_at(spaces, "enabled", DEFAULT_SPACES_ENABLED),
        switch_chance_percent=number_at(
            spaces,
            "switch_chance_percent",
            DEFAULT_SPACE_SWITCH_CHANCE_PERCENT,
        ),
        switch_step_seconds=number_at(
            spaces,
            "switch_step_seconds",
            SPACE_SWITCH_STEP_SECONDS,
        ),
        same_display_only=bool_at(
            spaces,
            "same_display_only",
            DEFAULT_SAME_DISPLAY_ONLY,
        ),
        config=SpaceConfig(spaces),
    )
    debug_config = DebugConfig(
        activity=ActivityConfig(
            window_seconds=number_at(debug, "window_seconds", 10),
            min_percent=number_at(debug, "min_percent", 20),
            max_percent=number_at(debug, "max_percent", 40),
        ),
        space_switch_chance_percent=number_at(
            debug,
            "space_switch_chance_percent",
            spaces_config.switch_chance_percent,
        ),
    )
    update_config = UpdateConfig(
        check_on_start=bool_at(
            updates,
            "check_on_start",
            DEFAULT_UPDATE_CHECK_ON_START,
        ),
        strategy=string_at(updates, "strategy", DEFAULT_UPDATE_STRATEGY),
        remote=string_at(updates, "remote", DEFAULT_UPDATE_REMOTE),
        branch=string_at(updates, "branch", DEFAULT_UPDATE_BRANCH),
        timeout_seconds=number_at(
            updates,
            "timeout_seconds",
            DEFAULT_UPDATE_TIMEOUT_SECONDS,
        ),
    )

    app_config = AppConfig(
        runtime=runtime_config,
        activity=activity_config,
        mouse=mouse_config,
        spaces=spaces_config,
        debug=debug_config,
        updates=update_config,
    )
    validate_config(app_config)
    return app_config


def number_at(config, key, default):
    value = config.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number")
    return float(value)


def bool_at(config, key, default):
    value = config.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    return value


def string_at(config, key, default):
    value = config.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def integer_at(config, key, default):
    value = number_at(config, key, default)
    if not value.is_integer():
        raise ValueError(f"{key} must be an integer")
    return int(value)


def validate_config(config):
    validate_activity_config(config.activity, "activity")
    validate_activity_config(config.debug.activity, "debug")

    if config.runtime.idle_seconds <= 0:
        raise ValueError("runtime.idle_seconds must be greater than 0")
    if config.runtime.poll_interval_seconds <= 0:
        raise ValueError("runtime.poll_interval_seconds must be greater than 0")
    if config.mouse.min_move_duration_seconds <= 0:
        raise ValueError("mouse.min_move_duration_seconds must be greater than 0")
    if config.mouse.max_move_duration_seconds <= 0:
        raise ValueError("mouse.max_move_duration_seconds must be greater than 0")
    if (
        config.mouse.min_move_duration_seconds
        > config.mouse.max_move_duration_seconds
    ):
        raise ValueError(
            "mouse.min_move_duration_seconds cannot exceed "
            "mouse.max_move_duration_seconds"
        )
    if config.mouse.wobble_pixels < 0:
        raise ValueError("mouse.wobble_pixels cannot be negative")
    if config.mouse.cancel_check_interval_seconds <= 0:
        raise ValueError("mouse.cancel_check_interval_seconds must be greater than 0")
    validate_percent(
        config.spaces.switch_chance_percent,
        "spaces.switch_chance_percent",
        allow_zero=True,
    )
    validate_percent(
        config.debug.space_switch_chance_percent,
        "debug.space_switch_chance_percent",
        allow_zero=True,
    )
    if config.spaces.switch_step_seconds <= 0:
        raise ValueError("spaces.switch_step_seconds must be greater than 0")
    if not config.updates.remote:
        raise ValueError("updates.remote cannot be empty")
    if config.updates.strategy not in UPDATE_STRATEGIES:
        strategies = ", ".join(sorted(UPDATE_STRATEGIES))
        raise ValueError(f"updates.strategy must be one of: {strategies}")
    if config.updates.timeout_seconds <= 0:
        raise ValueError("updates.timeout_seconds must be greater than 0")


def validate_activity_config(config, name):
    if config.window_seconds <= 0:
        raise ValueError(f"{name}.window_seconds must be greater than 0")
    validate_percent(config.min_percent, f"{name}.min_percent", allow_zero=False)
    validate_percent(config.max_percent, f"{name}.max_percent", allow_zero=False)
    if config.min_percent > config.max_percent:
        raise ValueError(f"{name}.min_percent cannot exceed {name}.max_percent")


def validate_percent(value, name, allow_zero):
    minimum = 0 if allow_zero else 0
    if value < minimum or value > 100:
        raise ValueError(f"{name} must be between {minimum} and 100")
    if not allow_zero and value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def effective_activity_config(config, debug):
    return config.debug.activity if debug else config.activity


def effective_space_switch_chance(config, debug):
    if debug:
        return config.debug.space_switch_chance_percent / 100
    return config.spaces.switch_chance_percent / 100


def build_activity_window(config, debug):
    activity_config = effective_activity_config(config, debug)
    return ActivityWindow(
        activity_config.window_seconds,
        activity_config.min_percent,
        activity_config.max_percent,
        config.mouse.min_move_duration_seconds,
        config.mouse.max_move_duration_seconds,
    )


def build_space_switcher(config, args):
    modes = selected_modes(args, config)
    if not modes.switch_spaces:
        return None

    return SpaceSwitcher(
        config.spaces.config,
        effective_space_switch_chance(config, args.debug),
        config.spaces.switch_step_seconds,
        config.spaces.same_display_only,
    )


def is_user_active(monitor, config):
    return monitor.idle_seconds() < config.runtime.idle_seconds


def main():
    args = parse_args()
    try:
        loaded_config = load_config_with_mtime()
    except RuntimeError as error:
        print(error)
        sys.exit(1)

    config = loaded_config.config
    modes = selected_modes(args, config)
    activity_config = effective_activity_config(config, args.debug)

    monitor = UserInputMonitor(initial_idle_seconds=config.runtime.idle_seconds)
    try:
        monitor.start()
    except RuntimeError as error:
        print(error)
        sys.exit(1)

    activity_window = build_activity_window(config, args.debug)
    space_switcher = build_space_switcher(config, args)
    was_paused = None

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0
    print("Press Ctrl-C to quit.")
    debug_log(args.debug, "Debug mode enabled.")
    debug_log(
        args.debug,
        (
            "Modes: "
            f"mouse_move={modes.mouse_move}, "
            f"switch_spaces={modes.switch_spaces}."
        ),
    )
    check_for_updates(config.updates, args.debug)

    while True:
        loaded_config, config_changed = reload_config_if_changed(loaded_config)
        if config_changed:
            config = loaded_config.config
            modes = selected_modes(args, config)
            activity_config = effective_activity_config(config, args.debug)
            activity_window = build_activity_window(config, args.debug)
            space_switcher = build_space_switcher(config, args)

        user_is_active = is_user_active(monitor, config)

        if user_is_active:
            if was_paused is not True:
                was_paused = True
                debug_log(args.debug, "Paused: user activity detected.")
            activity_window.moves = []
            if space_switcher:
                space_switcher.reset_window()
            time.sleep(config.runtime.poll_interval_seconds)
            continue

        if was_paused is not False:
            was_paused = False
            debug_log(args.debug, "Resumed: user is idle.")

        now = time.monotonic()
        if not activity_window.moves or activity_window.has_ended(now):
            activity_window.start(now)
            debug_log(
                args.debug,
                (
                    "New activity window: "
                    f"{len(activity_window.moves)} movements over "
                    f"{activity_config.window_seconds:g}s."
                ),
            )
            if space_switcher:
                try:
                    space_switcher.start_window(now, activity_config.window_seconds)
                except RuntimeError as error:
                    print(error)
                    sys.exit(1)

        scheduled_move = (
            activity_window.next_due_move(now)
            if modes.mouse_move
            else None
        )
        if scheduled_move:
            debug_log(args.debug, f"Moving mouse for {scheduled_move.duration:.1f}s.")
            moved = move_mouse(
                scheduled_move.duration,
                config.mouse,
                lambda: is_user_active(monitor, config),
            )
            if not moved:
                activity_window.moves = []
                if space_switcher:
                    space_switcher.reset_window()
                continue

        if space_switcher:
            try:
                switched = space_switcher.switch_if_due(
                    time.monotonic(),
                    lambda: is_user_active(monitor, config),
                )
            except RuntimeError as error:
                print(error)
                sys.exit(1)
            if not switched:
                activity_window.moves = []
                space_switcher.reset_window()
                continue

        time.sleep(config.runtime.poll_interval_seconds)


def debug_log(enabled, message):
    if enabled:
        print(message)


def stop(signum, frame):
    print("\nStopped.")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop)
    main()
