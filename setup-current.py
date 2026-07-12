#!/usr/bin/env python3
"""Install the public HYP consultation plugin for one local AI client.

The repository never contains the HYP bearer token. This installer obtains it
from HYP_MCP_TOKEN or a local password dialog, verifies it, and stores it only
in the current user's local configuration.
"""

from __future__ import annotations

import getpass
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


PLUGIN = "hyp-consult-agent@hyp-consult-agent"
PLUGIN_NAME = "hyp-consult-agent"
SKILL_CACHE_COMPAT_NAME = "hyp-consult"
SERVER_NAME = "hyp-knowledge"
TOKEN_ENV = "HYP_MCP_TOKEN"
REMOTE_URL = "https://hyp-knowledge-mcp.bijiadaxiong.workers.dev/mcp"
SMOKE_USER_AGENT = "hyp-consult-agent-setup/0.2.22"
CLIENT_ALIASES = {
    "codex": "codex",
    "claude": "claude-code",
    "claude-code": "claude-code",
    "claudecode": "claude-code",
    "cursor": "cursor",
    "antigravity": "antigravity",
    "ag": "antigravity",
    "agy": "antigravity",
    "gemini": "antigravity",
}


def bundle_root() -> Path:
    return Path(__file__).resolve().parent


def normalize_client(value: str | None) -> str | None:
    if not value:
        return None
    return CLIENT_ALIASES.get(value.strip().lower().replace("_", "-"))


def process_chain() -> list[str]:
    if sys.platform.startswith("win"):
        return []
    chain: list[str] = []
    pid = os.getppid()
    for _ in range(10):
        if pid <= 1:
            break
        try:
            command = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)],
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
            ppid_text = subprocess.run(
                ["ps", "-o", "ppid=", "-p", str(pid)],
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
        except OSError:
            break
        if command:
            chain.append(command)
        try:
            pid = int(ppid_text)
        except ValueError:
            break
    return chain


def detect_current_client() -> str | None:
    explicit = normalize_client(os.getenv("HYP_SETUP_CLIENT"))
    if explicit:
        return explicit
    env = os.environ
    if env.get("CODEX_HOME") or env.get("CODEX_SESSION_ID"):
        return "codex"
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    if env.get("CURSOR_TRACE_ID") or env.get("CURSOR_WORKSPACE_ID"):
        return "cursor"
    if env.get("ANTIGRAVITY") or env.get("AGY_SESSION_ID"):
        return "antigravity"
    for command in process_chain():
        text = command.lower()
        if "codex" in text:
            return "codex"
        if "claude" in text:
            return "claude-code"
        if "cursor" in text:
            return "cursor"
        if "antigravity" in text or "agy" in text:
            return "antigravity"
    return None


def parse_args() -> tuple[str | None, str, bool, bool]:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    no_prompt = "--no-prompt" in args
    args = [arg for arg in args if arg not in {"--dry-run", "--no-prompt"}]
    target = normalize_client(args[0]) if args else None
    if target:
        args = args[1:]
    else:
        target = detect_current_client()
    source = args[0] if args else str(bundle_root())
    return target, source, dry_run, no_prompt


def prompt_macos_token() -> str:
    script = (
        'set answerResult to display dialog "HYP MCPアクセストークンを入力してください。" '
        'default answer "" with hidden answer buttons {"キャンセル", "設定"} '
        'default button "設定" cancel button "キャンセル"\n'
        'return text returned of answerResult'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def prompt_windows_token() -> str:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return ""
    script = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = 'HYP MCP authentication'
$form.Size = New-Object System.Drawing.Size(480,180)
$form.StartPosition = 'CenterScreen'
$label = New-Object System.Windows.Forms.Label
$label.Text = 'HYP MCP access token:'
$label.Location = New-Object System.Drawing.Point(16,20)
$label.AutoSize = $true
$box = New-Object System.Windows.Forms.TextBox
$box.Location = New-Object System.Drawing.Point(20,50)
$box.Size = New-Object System.Drawing.Size(425,24)
$box.UseSystemPasswordChar = $true
$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'Save'
$ok.Location = New-Object System.Drawing.Point(285,95)
$ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
$cancel = New-Object System.Windows.Forms.Button
$cancel.Text = 'Cancel'
$cancel.Location = New-Object System.Drawing.Point(370,95)
$cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.Controls.AddRange(@($label,$box,$ok,$cancel))
$form.AcceptButton = $ok
$form.CancelButton = $cancel
if ($form.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::Out.Write($box.Text)
}
'''
    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", script],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def prompt_token() -> str:
    if sys.platform == "darwin" and shutil.which("osascript"):
        token = prompt_macos_token()
        if token:
            return token
    if sys.platform.startswith("win"):
        token = prompt_windows_token()
        if token:
            return token
    if shutil.which("zenity"):
        result = subprocess.run(
            ["zenity", "--password", "--title=HYP MCP authentication"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    if sys.stdin.isatty():
        return getpass.getpass("HYP MCP access token: ")
    return ""


def resolve_token(no_prompt: bool) -> str:
    # Interactive installs must always ask the user. A long-running AI client
    # can retain an old token in its process environment even after local
    # settings were removed, which would otherwise bypass the password dialog.
    token = os.getenv(TOKEN_ENV, "").strip() if no_prompt else prompt_token().strip()
    if token.startswith("Bearer "):
        token = token[len("Bearer ") :].strip()
    if not token:
        raise RuntimeError(
            "No HYP MCP token was provided. Set HYP_MCP_TOKEN or run the installer interactively."
        )
    if any(char in token for char in "\r\n\0"):
        raise RuntimeError("The HYP MCP token contains invalid control characters.")
    return token


def verify_remote(token: str) -> dict:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ).encode("utf-8")
    request = urllib.request.Request(
        REMOTE_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": SMOKE_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
            tools = data.get("result", {}).get("tools", [])
            return {
                "label": "remote_mcp_smoke",
                "status": "ok",
                "http_status": response.status,
                "tool_count": len(tools),
            }
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            reason = "The HYP MCP access token was rejected."
        elif exc.code == 403:
            reason = "Cloudflare denied the request before or during authentication."
        else:
            reason = f"Remote MCP returned HTTP {exc.code}."
        return {
            "label": "remote_mcp_smoke",
            "status": "failed",
            "http_status": exc.code,
            "reason": reason,
        }
    except Exception as exc:
        return {
            "label": "remote_mcp_smoke",
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def replace_setting(path: Path, prefixes: tuple[str, ...], line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(errors="replace").splitlines() if path.exists() else []
    kept = [item for item in existing if not item.strip().startswith(prefixes)]
    path.write_text("\n".join([*kept, line, ""]))


def persist_token(token: str, dry_run: bool = False) -> dict:
    codex_env = Path.home() / ".codex" / ".env"
    if dry_run:
        return {
            "label": "token_storage",
            "status": "dry_run",
            "locations": [str(codex_env), "user environment"],
        }
    os.environ[TOKEN_ENV] = token
    replace_setting(codex_env, (f"{TOKEN_ENV}=", f"export {TOKEN_ENV}="), f"{TOKEN_ENV}={token}")
    try:
        codex_env.chmod(0o600)
    except OSError:
        pass

    locations = [str(codex_env)]
    if sys.platform.startswith("win"):
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, TOKEN_ENV, 0, winreg.REG_SZ, token)
        locations.append("Windows user environment")
    else:
        shell_rc = Path.home() / (".zshrc" if shutil.which("zsh") else ".bashrc")
        replace_setting(
            shell_rc,
            (f"{TOKEN_ENV}=", f"export {TOKEN_ENV}="),
            f"export {TOKEN_ENV}={shlex.quote(token)}",
        )
        locations.append(str(shell_rc))
    return {"label": "token_storage", "status": "ok", "locations": locations}


def patch_runtime_auth(path: Path, token: str) -> None:
    data = read_json(path)
    if "mcpServers" in data:
        server = data["mcpServers"].get(SERVER_NAME, {})
    else:
        server = data.get(SERVER_NAME, {})
    uses_codex_headers = "bearer_token_env_var" in server or "http_headers" in server
    server.pop("bearer_token_env_var", None)
    server.pop("env_http_headers", None)
    header_key = "http_headers" if uses_codex_headers else "headers"
    server.pop("http_headers" if header_key == "headers" else "headers", None)
    server[header_key] = {"Authorization": f"Bearer {token}"}
    write_json(path, data)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def stage_authenticated_marketplace(token: str, dry_run: bool = False) -> tuple[dict, str]:
    destination = Path.home() / ".hyp-consult-agent" / "marketplace"
    if dry_run:
        return (
            {
                "label": "authenticated_marketplace",
                "status": "dry_run",
                "path": str(destination),
            },
            str(destination),
        )

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, mode=0o700)
    included = [
        ".agents",
        ".claude-plugin",
        ".cursor-plugin",
        "plugins",
        "antigravity-plugin",
        "skills",
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        ".mcp.json",
    ]
    for name in included:
        source = bundle_root() / name
        target = destination / name
        if not source.exists():
            continue
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
            )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    auth_files = [
        destination / "plugins" / PLUGIN_NAME / ".mcp.json",
        destination / "plugins" / f"{PLUGIN_NAME}-claude-code" / ".mcp.json",
        destination / "antigravity-plugin" / PLUGIN_NAME / "mcp_config.json",
        destination / ".mcp.json",
    ]
    patched = []
    for path in auth_files:
        if path.exists():
            patch_runtime_auth(path, token)
            patched.append(str(path))

    if len(patched) < 2:
        raise RuntimeError("authenticated marketplace is missing expected MCP configuration files")
    for directory in [destination, *[path for path in destination.rglob("*") if path.is_dir()]]:
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    return (
        {
            "label": "authenticated_marketplace",
            "status": "ok",
            "path": str(destination),
            "patched_config_count": len(patched),
        },
        str(destination),
    )


def run(label: str, command: list[str], dry_run: bool = False) -> dict:
    if dry_run:
        return {"label": label, "status": "dry_run", "command": command}
    executable = shutil.which(command[0])
    if not executable:
        return {
            "label": label,
            "status": "failed",
            "reason": f"{command[0]} CLI not found",
            "command": command,
        }
    result = subprocess.run(
        [executable, *command[1:]],
        text=True,
        capture_output=True,
        check=False,
    )
    combined = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    ok = result.returncode == 0 or (
        "already" in combined.lower()
        and any(word in combined.lower() for word in ["install", "exist", "configured", "added"])
    )
    return {
        "label": label,
        "status": "ok" if ok else "failed",
        "returncode": result.returncode,
        "command": command,
        "output": combined[-2000:],
    }


def run_cleanup(label: str, command: list[str], dry_run: bool = False) -> dict:
    result = run(label, command, dry_run)
    if dry_run or result.get("status") == "ok":
        return result
    output = str(result.get("output") or "").lower()
    if any(
        phrase in output
        for phrase in (
            "not installed",
            "not found",
            "does not exist",
            "no marketplace",
            "unknown plugin",
        )
    ):
        result["status"] = "ok"
        result["cleanup_note"] = "already absent"
    return result


def clear_codex_plugin_cache(dry_run: bool = False) -> dict:
    codex_home = Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex"))
    cache_root = codex_home / "plugins" / "cache" / PLUGIN_NAME
    if dry_run:
        return {"label": "codex_stale_cache", "status": "dry_run", "path": str(cache_root)}
    if cache_root.exists():
        shutil.rmtree(cache_root)
    return {"label": "codex_stale_cache", "status": "ok", "path": str(cache_root)}


def verify_codex_plugin_version(dry_run: bool = False) -> dict:
    expected = str(
        read_json(bundle_root() / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json").get(
            "version"
        )
        or ""
    )
    if dry_run:
        return {
            "label": "codex_plugin_version",
            "status": "dry_run",
            "expected": expected,
        }
    executable = shutil.which("codex")
    if not executable:
        return {"label": "codex_plugin_version", "status": "failed", "reason": "codex CLI not found"}
    result = subprocess.run(
        [executable, "plugin", "list", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        installed = json.loads(result.stdout).get("installed", [])
    except json.JSONDecodeError:
        installed = []
    match = next((item for item in installed if item.get("pluginId") == PLUGIN), None)
    actual = str((match or {}).get("version") or "")
    return {
        "label": "codex_plugin_version",
        "status": "ok" if actual == expected and expected else "failed",
        "expected": expected,
        "actual": actual or None,
        **({} if actual == expected and expected else {"reason": "installed plugin version mismatch"}),
    }


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".hyp-consult-agent.bak")
        backup.write_text(path.read_text())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def copy_tree_replacing(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return True


def install_codex_cache_compat(dry_run: bool = False) -> dict:
    manifest = read_json(bundle_root() / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json")
    version = str(manifest.get("version") or "").strip()
    codex_home = Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex"))
    cache_root = codex_home / "plugins" / "cache" / PLUGIN_NAME
    source = cache_root / PLUGIN_NAME / version
    destinations = [cache_root / version, cache_root / SKILL_CACHE_COMPAT_NAME / version]
    if dry_run:
        return {
            "label": "codex_skill_path_compat",
            "status": "dry_run",
            "source": str(source),
            "paths": [str(path) for path in destinations],
        }
    if not version or not source.exists():
        return {
            "label": "codex_skill_path_compat",
            "status": "skipped",
            "reason": f"installed Codex plugin cache not found: {source}",
        }
    for destination in destinations:
        copy_tree_replacing(source, destination)
    return {
        "label": "codex_skill_path_compat",
        "status": "ok",
        "paths": [str(path) for path in destinations],
    }


def configure_cursor(token: str, dry_run: bool = False) -> dict:
    path = Path.home() / ".cursor" / "mcp.json"
    if dry_run:
        return {"label": "cursor_mcp", "status": "dry_run", "path": str(path)}
    if not path.parent.exists():
        return {"label": "cursor_mcp", "status": "failed", "reason": "~/.cursor not found"}
    data = read_json(path)
    data.setdefault("mcpServers", {})[SERVER_NAME] = {
        "url": REMOTE_URL,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    write_json(path, data)
    return {"label": "cursor_mcp", "status": "ok", "path": str(path)}


def configure_antigravity(token: str, dry_run: bool = False) -> list[dict]:
    plugin_source = bundle_root() / "antigravity-plugin" / PLUGIN_NAME
    plugin_dest = Path.home() / ".gemini" / "config" / "plugins" / PLUGIN_NAME
    config_path = Path.home() / ".gemini" / "antigravity" / "mcp_config.json"
    if dry_run:
        return [
            {"label": "antigravity_plugin", "status": "dry_run", "path": str(plugin_dest)},
            {"label": "antigravity_mcp", "status": "dry_run", "path": str(config_path)},
        ]
    if not (Path.home() / ".gemini").exists():
        return [{"label": "antigravity", "status": "failed", "reason": "~/.gemini not found"}]
    copy_tree_replacing(plugin_source, plugin_dest)
    data = read_json(config_path)
    data.setdefault("mcpServers", {})[SERVER_NAME] = {
        "serverUrl": REMOTE_URL,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    write_json(config_path, data)
    return [
        {"label": "antigravity_plugin", "status": "ok", "path": str(plugin_dest)},
        {"label": "antigravity_mcp", "status": "ok", "path": str(config_path)},
    ]


def setup_target(target: str, source: str, token: str, dry_run: bool) -> list[dict]:
    if target == "codex":
        return [
            run_cleanup("codex_old_plugin", ["codex", "plugin", "remove", PLUGIN], dry_run),
            run_cleanup(
                "codex_old_marketplace",
                ["codex", "plugin", "marketplace", "remove", PLUGIN_NAME],
                dry_run,
            ),
            clear_codex_plugin_cache(dry_run),
            run("codex_marketplace", ["codex", "plugin", "marketplace", "add", source], dry_run),
            run("codex_plugin", ["codex", "plugin", "add", PLUGIN], dry_run),
            install_codex_cache_compat(dry_run),
            verify_codex_plugin_version(dry_run),
        ]
    if target == "claude-code":
        return [
            run_cleanup(
                "claude_old_plugin",
                ["claude", "plugin", "uninstall", "--scope", "user", PLUGIN],
                dry_run,
            ),
            run_cleanup(
                "claude_old_marketplace",
                ["claude", "plugin", "marketplace", "remove", PLUGIN_NAME],
                dry_run,
            ),
            run("claude_marketplace", ["claude", "plugin", "marketplace", "add", source], dry_run),
            run("claude_plugin", ["claude", "plugin", "install", "--scope", "user", PLUGIN], dry_run),
        ]
    if target == "cursor":
        return [configure_cursor(token, dry_run)]
    if target == "antigravity":
        return configure_antigravity(token, dry_run)
    return [{"label": "target", "status": "failed", "reason": f"unknown target: {target}"}]


def next_steps(target: str) -> list[str]:
    return {
        "codex": [
            "Quit Codex completely and reopen it. Starting a new task without restarting is not sufficient."
        ],
        "claude-code": ["Open a new terminal and start a new Claude Code session."],
        "cursor": ["Restart Cursor."],
        "antigravity": ["Restart Antigravity."],
    }.get(target, [])


def main() -> int:
    target, source, dry_run, no_prompt = parse_args()
    if not target:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": "Could not detect the client. Pass codex, claude-code, cursor, or antigravity.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    token = "" if dry_run else resolve_token(no_prompt)
    smoke = {"label": "remote_mcp_smoke", "status": "dry_run"} if dry_run else verify_remote(token)
    if smoke["status"] == "failed":
        print(json.dumps({"status": "failed", "results": [smoke]}, ensure_ascii=False, indent=2))
        return 1

    runtime_result, runtime_source = stage_authenticated_marketplace(token, dry_run)
    results = [
        persist_token(token, dry_run),
        runtime_result,
        *setup_target(target, runtime_source, token, dry_run),
        smoke,
    ]
    failed = any(item.get("status") == "failed" for item in results)
    summary = {
        "status": "failed" if failed else "ok",
        "target": target,
        "source": source,
        "runtime_source": runtime_source,
        "dry_run": dry_run,
        "client_restart_required": target == "codex" and not dry_run,
        "results": results,
        "next_steps": next_steps(target),
    }
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if token and token in output:
        raise RuntimeError("refusing to print a summary containing the access token")
    print(output)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
