#!/usr/bin/env python3
"""Safely update hyp-consult-agent from its official GitHub releases."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


PLUGIN_ID = "hyp-consult-agent@hyp-consult-agent"
PLUGIN_NAME = "hyp-consult-agent"
TOKEN_ENV = "HYP_MCP_TOKEN"
REPOSITORY = "sam-mountainman/hyp-consult-agent"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
UPDATE_ROOT = Path.home() / ".hyp-consult-agent" / "updater"
STATE_PATH = UPDATE_ROOT / "update-state.json"
LOCK_PATH = UPDATE_ROOT / "update.lock"
LAUNCH_AGENT_LABEL = "com.hyp-consult-agent.autoupdate"
WINDOWS_TASK_NAME = "HYP Consult Agent Auto Update"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def print_json(payload: dict) -> None:
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    token = resolve_saved_token(required=False)
    if token and token in output:
        raise RuntimeError("refusing to print updater output containing the HYP token")
    print(output)


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    match = VERSION_RE.fullmatch((value or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def normalize_version(value: str) -> str:
    parsed = parse_version(value)
    if not parsed:
        raise RuntimeError(f"unsupported release version: {value}")
    return ".".join(str(part) for part in parsed)


def run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(command[0])
    if not executable:
        return subprocess.CompletedProcess(
            command, 127, "", f"{command[0]} CLI not found"
        )
    return subprocess.run(
        [executable, *command[1:]],
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def codex_version() -> str | None:
    result = run(["codex", "plugin", "list", "--json"])
    if result.returncode != 0:
        return None
    try:
        items = json.loads(result.stdout).get("installed", [])
    except json.JSONDecodeError:
        return None
    match = next((item for item in items if item.get("pluginId") == PLUGIN_ID), None)
    return str((match or {}).get("version") or "") or None


def claude_version() -> str | None:
    result = run(["claude", "plugin", "list", "--json"])
    if result.returncode != 0:
        return None
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    match = next((item for item in items if item.get("id") == PLUGIN_ID), None)
    return str((match or {}).get("version") or "") or None


def installed_versions() -> dict[str, str]:
    versions = {"codex": codex_version(), "claude-code": claude_version()}
    return {client: version for client, version in versions.items() if version}


def parse_env_file(path: Path) -> str:
    if not path.exists():
        return ""
    for raw_line in path.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line.startswith(f"{TOKEN_ENV}="):
            continue
        value = line.split("=", 1)[1].strip().strip("\"'")
        return value.removeprefix("Bearer ").strip()
    return ""


def token_from_runtime() -> str:
    candidates = [
        Path.home()
        / ".hyp-consult-agent"
        / "marketplace"
        / "plugins"
        / PLUGIN_NAME
        / ".mcp.json",
        Path.home()
        / ".hyp-consult-agent"
        / "marketplace"
        / "plugins"
        / f"{PLUGIN_NAME}-claude-code"
        / ".mcp.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text())
            server = payload.get("mcpServers", {}).get("hyp-knowledge", {})
            headers = server.get("http_headers") or server.get("headers") or {}
            value = str(headers.get("Authorization") or "")
        except (OSError, json.JSONDecodeError):
            continue
        if value.startswith("Bearer "):
            return value[len("Bearer ") :].strip()
    return ""


def resolve_saved_token(required: bool = True) -> str:
    token = os.getenv(TOKEN_ENV, "").removeprefix("Bearer ").strip()
    if not token:
        token = parse_env_file(Path.home() / ".codex" / ".env")
    if not token:
        token = token_from_runtime()
    if required and not token:
        raise RuntimeError(
            "HYP MCP token is not available locally. Run setup-current.py interactively once."
        )
    if token and any(char in token for char in "\r\n\0"):
        raise RuntimeError("stored HYP MCP token contains invalid control characters")
    return token


def fetch_latest_release(api_url: str = RELEASE_API) -> dict:
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hyp-consult-agent-updater",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("draft") or payload.get("prerelease"):
        raise RuntimeError("latest GitHub release is not a stable release")
    version = normalize_version(str(payload.get("tag_name") or ""))
    archive_url = str(payload.get("zipball_url") or "")
    if not archive_url.startswith(
        f"https://api.github.com/repos/{REPOSITORY}/zipball/"
    ):
        raise RuntimeError(
            "GitHub release archive URL did not match the official repository"
        )
    return {
        "version": version,
        "archive_url": archive_url,
        "html_url": payload.get("html_url"),
    }


def safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        destination_root = destination.resolve()
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            try:
                target.relative_to(destination_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"release archive contains an unsafe path: {member.filename}"
                ) from exc
        bundle.extractall(destination)


def validate_release_bundle(root: Path, expected_version: str) -> None:
    paths = [
        root / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json",
        root
        / "plugins"
        / f"{PLUGIN_NAME}-claude-code"
        / ".claude-plugin"
        / "plugin.json",
    ]
    versions: list[str] = []
    for path in paths:
        if not path.exists():
            raise RuntimeError(
                f"release is missing required manifest: {path.relative_to(root)}"
            )
        versions.append(str(json.loads(path.read_text()).get("version") or ""))
    required = ["setup-current.py", "update-current.py", ".agents", ".claude-plugin"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise RuntimeError(f"release is missing updater files: {', '.join(missing)}")
    if any(version != expected_version for version in versions):
        raise RuntimeError(
            f"release tag and plugin manifests disagree: tag={expected_version}, manifests={versions}"
        )


def download_release(release: dict, destination: Path) -> Path:
    archive = destination / "release.zip"
    request = urllib.request.Request(
        release["archive_url"], headers={"User-Agent": "hyp-consult-agent-updater"}
    )
    with urllib.request.urlopen(request, timeout=120) as response, archive.open(
        "wb"
    ) as handle:
        shutil.copyfileobj(response, handle)
    extracted = destination / "extracted"
    extracted.mkdir()
    safe_extract(archive, extracted)
    roots = [path.parent for path in extracted.rglob("setup-current.py")]
    roots = [path for path in roots if (path / "plugins" / PLUGIN_NAME).exists()]
    if len(roots) != 1:
        raise RuntimeError(f"expected one release root, found {len(roots)}")
    validate_release_bundle(roots[0], release["version"])
    return roots[0]


def load_setup_module(root: Path):
    spec = importlib.util.spec_from_file_location(
        "hyp_release_setup", root / "setup-current.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load downloaded setup-current.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_release_mcp(root: Path, token: str) -> dict:
    result = load_setup_module(root).verify_remote(token)
    if result.get("status") != "ok":
        raise RuntimeError(
            str(result.get("reason") or "downloaded release failed MCP verification")
        )
    return result


def redact(text: str, token: str) -> str:
    return text.replace(token, "[REDACTED]") if token else text


def run_release_setup(root: Path, client: str, token: str) -> dict:
    env = os.environ.copy()
    env[TOKEN_ENV] = token
    result = subprocess.run(
        [
            sys.executable,
            str(root / "setup-current.py"),
            client,
            "--no-prompt",
            "--no-auto-update",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        env=env,
    )
    output = redact(
        "\n".join(part for part in (result.stdout, result.stderr) if part), token
    )
    return {
        "client": client,
        "status": "ok" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "output": output[-4000:],
    }


def runtime_for(version: str | None) -> Path | None:
    if not version:
        return None
    root = UPDATE_ROOT / "releases" / version
    return root if (root / "setup-current.py").exists() else None


def rollback_clients(previous: dict[str, str], token: str) -> list[dict]:
    results: list[dict] = []
    for client, version in previous.items():
        root = runtime_for(version)
        if root is None:
            results.append(
                {
                    "client": client,
                    "status": "failed",
                    "reason": f"rollback runtime for {version} is unavailable",
                }
            )
            continue
        result = run_release_setup(root, client, token)
        result["rollback_version"] = version
        results.append(result)
    return results


def write_state(payload: dict) -> None:
    UPDATE_ROOT.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    try:
        STATE_PATH.chmod(0o600)
    except OSError:
        pass


@contextlib.contextmanager
def update_lock():
    UPDATE_ROOT.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists() and time.time() - LOCK_PATH.stat().st_mtime > 7200:
        LOCK_PATH.unlink()
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            "another hyp-consult-agent update is already running"
        ) from exc
    os.close(descriptor)
    try:
        yield
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def stable_updater_path() -> Path:
    return UPDATE_ROOT / "update-current.py"


def scheduler_path() -> str:
    entries = [str(Path(sys.executable).resolve().parent)]
    for command in ("codex", "claude"):
        executable = shutil.which(command)
        if executable:
            entries.append(str(Path(executable).resolve().parent))
    entries.extend(os.environ.get("PATH", "").split(os.pathsep))
    deduplicated: list[str] = []
    for entry in entries:
        if entry and entry not in deduplicated:
            deduplicated.append(entry)
    return os.pathsep.join(deduplicated)


def install_macos_schedule() -> dict:
    updater = stable_updater_path()
    if not updater.exists():
        raise RuntimeError(f"installed updater not found: {updater}")
    logs = UPDATE_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            sys.executable,
            str(updater),
            "all-installed",
            "--no-prompt",
        ],
        "StartCalendarInterval": {"Hour": 11, "Minute": 15},
        "StandardOutPath": str(logs / "update.log"),
        "StandardErrorPath": str(logs / "update-error.log"),
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "PATH": scheduler_path(),
        },
    }
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", domain, str(path)], capture_output=True, check=False
    )
    loaded = subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if loaded.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {loaded.stderr.strip()}")
    return {
        "status": "ok",
        "scheduler": "launchd",
        "path": str(path),
        "daily_at": "11:15",
    }


def install_windows_schedule() -> dict:
    updater = stable_updater_path()
    if not updater.exists():
        raise RuntimeError(f"installed updater not found: {updater}")
    logs = UPDATE_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    launcher = UPDATE_ROOT / "auto-update.cmd"
    launcher.write_text(
        f'@echo off\r\nset "PATH={scheduler_path()};%PATH%"\r\n'
        f'"{sys.executable}" "{updater}" all-installed --no-prompt '
        f'>> "{logs / "update.log"}" 2>&1\r\n'
    )
    result = subprocess.run(
        [
            "schtasks.exe",
            "/Create",
            "/TN",
            WINDOWS_TASK_NAME,
            "/TR",
            f'"{launcher}"',
            "/SC",
            "DAILY",
            "/ST",
            "11:15",
            "/F",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Task Scheduler setup failed: {result.stderr or result.stdout}"
        )
    return {
        "status": "ok",
        "scheduler": "Task Scheduler",
        "path": str(launcher),
        "daily_at": "11:15",
    }


def install_linux_schedule() -> dict:
    updater = stable_updater_path()
    if not updater.exists():
        raise RuntimeError(f"installed updater not found: {updater}")
    unit_root = Path.home() / ".config" / "systemd" / "user"
    unit_root.mkdir(parents=True, exist_ok=True)
    service = unit_root / "hyp-consult-agent-update.service"
    timer = unit_root / "hyp-consult-agent-update.timer"
    service.write_text(
        "[Unit]\nDescription=Update hyp-consult-agent\n\n[Service]\nType=oneshot\n"
        f'Environment="PATH={scheduler_path()}"\n'
        f'ExecStart="{sys.executable}" "{updater}" all-installed --no-prompt\n'
    )
    timer.write_text(
        "[Unit]\nDescription=Daily hyp-consult-agent update check\n\n[Timer]\n"
        "OnCalendar=*-*-* 11:15:00\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", timer.name], check=True)
    return {
        "status": "ok",
        "scheduler": "systemd",
        "path": str(timer),
        "daily_at": "11:15",
    }


def install_schedule() -> dict:
    if sys.platform == "darwin":
        return install_macos_schedule()
    if sys.platform.startswith("win"):
        return install_windows_schedule()
    return install_linux_schedule()


def remove_schedule() -> dict:
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}", str(path)],
            capture_output=True,
            check=False,
        )
        path.unlink(missing_ok=True)
        return {"status": "ok", "scheduler": "launchd", "removed": str(path)}
    if sys.platform.startswith("win"):
        subprocess.run(
            ["schtasks.exe", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"],
            capture_output=True,
            check=False,
        )
        return {"status": "ok", "scheduler": "Task Scheduler"}
    timer = (
        Path.home() / ".config" / "systemd" / "user" / "hyp-consult-agent-update.timer"
    )
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", timer.name],
        capture_output=True,
        check=False,
    )
    timer.unlink(missing_ok=True)
    timer.with_name("hyp-consult-agent-update.service").unlink(missing_ok=True)
    return {"status": "ok", "scheduler": "systemd"}


def selected_clients(target: str, installed: dict[str, str]) -> list[str]:
    if target == "all-installed":
        return [client for client in ("codex", "claude-code") if client in installed]
    return [target]


def update(
    target: str, check_only: bool, force: bool, dry_run: bool, api_url: str
) -> dict:
    current = installed_versions()
    clients = selected_clients(target, current)
    if not clients:
        return {
            "status": "skipped",
            "reason": "hyp-consult-agent is not installed in Codex or Claude Code",
            "installed_versions": current,
        }
    release = fetch_latest_release(api_url)
    latest_tuple = parse_version(release["version"])
    needs_update = [
        client
        for client in clients
        if force
        or client not in current
        or (parse_version(current.get(client)) or (0, 0, 0)) < latest_tuple
    ]
    base = {
        "installed_versions": current,
        "latest_version": release["version"],
        "release_url": release["html_url"],
        "clients": clients,
    }
    if check_only or dry_run:
        return {
            **base,
            "status": "update_available" if needs_update else "current",
            "dry_run": dry_run,
        }
    if not needs_update:
        write_state({**base, "status": "current"})
        return {**base, "status": "current"}

    token = resolve_saved_token()
    with tempfile.TemporaryDirectory(prefix="hyp-consult-agent-update-") as temp:
        root = download_release(release, Path(temp))
        smoke = verify_release_mcp(root, token)
        install_results: list[dict] = []
        previous = {
            client: current[client] for client in needs_update if client in current
        }
        for client in needs_update:
            result = run_release_setup(root, client, token)
            install_results.append(result)
            if result["status"] != "ok":
                rollback = rollback_clients(previous, token)
                failure = {
                    **base,
                    "status": "failed",
                    "failed_client": client,
                    "results": install_results,
                    "rollback": rollback,
                }
                write_state(failure)
                return failure
        actual = installed_versions()
        mismatched = {
            client: actual.get(client)
            for client in needs_update
            if actual.get(client) != release["version"]
        }
        if mismatched:
            rollback = rollback_clients(previous, token)
            failure = {
                **base,
                "status": "failed",
                "reason": f"installed version verification failed: {mismatched}",
                "results": install_results,
                "rollback": rollback,
            }
            write_state(failure)
            return failure
        success = {
            **base,
            "status": "updated",
            "updated_clients": needs_update,
            "installed_versions_after": actual,
            "mcp_smoke": smoke,
            "restart_required": needs_update,
        }
        write_state(success)
        return success


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default="all-installed",
        choices=("codex", "claude-code", "all-installed"),
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-prompt", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--install-schedule", action="store_true")
    parser.add_argument("--remove-schedule", action="store_true")
    parser.add_argument(
        "--release-api", default=os.getenv("HYP_UPDATE_RELEASE_API", RELEASE_API)
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.install_schedule:
            print_json(install_schedule())
            return 0
        if args.remove_schedule:
            print_json(remove_schedule())
            return 0
        with update_lock():
            result = update(
                args.target,
                check_only=args.check_only,
                force=args.force,
                dry_run=args.dry_run,
                api_url=args.release_api,
            )
        print_json(result)
        return 1 if result.get("status") == "failed" else 0
    except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        payload = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        write_state(payload)
        print_json(payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
