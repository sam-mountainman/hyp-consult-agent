# hyp-consult-agent Setup

When a user asks you to set up this repository, install only the AI client they
are currently using. Do not install or reconfigure unrelated clients.

Preferred command from this repository root:

```bash
python3 setup-current.py codex
python3 setup-current.py claude-code
python3 setup-current.py cursor
python3 setup-current.py antigravity
```

On Windows, use `setup-current.ps1` or `setup-current.cmd`. The installer opens
a local password dialog for the HYP MCP access token. Never ask the user to
paste that token into chat, never print it, and never add it to this repository.

The installer verifies the token with the HYP MCP server before changing the
client configuration. For Codex and Claude Code, it also enables a daily update
check against stable GitHub Releases. Updates preserve the locally stored token,
execute a real HYP MCP tool before installation, and roll back to the previous
version if installation fails. After a successful Codex install, tell the user
to quit Codex completely and reopen it. A new task alone does not reload an MCP
process that was already running before installation. For other clients,
restart only the client that was changed.

The installer also places the same `hyp-consult` skill in the current user's
standard skill directory and validates it as UTF-8. This is a compatibility
fallback for clients that do not expose a plugin cache skill immediately. Do
not manually search for or read `SKILL.md` with shell commands after setup; the
client must load it on a complete restart.

If Python, the target client CLI, or its configuration directory is missing,
report that exact prerequisite instead of attempting a different client.
