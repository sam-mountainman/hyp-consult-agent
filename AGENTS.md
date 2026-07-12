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
client configuration. After a successful install, restart only the client that
was changed or start a new session/task.

If Python, the target client CLI, or its configuration directory is missing,
report that exact prerequisite instead of attempting a different client.
