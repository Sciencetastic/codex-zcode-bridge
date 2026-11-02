# Experimental live desktop chat adapter

Send a prompt from an external controller and see it, tool activity and the reply in an
already-open ZCode desktop chat. Read the visible reply back without taking over the screen.

This is an **opt-in experimental local patch**, separate from the standard Bridge MCP tools.
Observed working on Windows ZCode **3.17.1**, original app.asar SHA256
`9a09f6ef7a938072c57f56d3dbf4b5677eaceb1c5b00ae555fb7e2bfdea88255`.
Other builds are refused. The application may replace the patch when it updates.
No ZCode binaries or extracted ZCode source are distributed here.

The adapter shares the desktop's existing workspace host over its MessagePort instead of
launching a separate app-server. In the local proof, a prompt, Working state and the complete
assistant reply appeared in the open chat without refresh/navigation; the controller read the
same reply. A subsequent bounded development task also appeared in that chat.
Phone viewing has **not** been tested. No remote terminal ownership is requested.

## Setup (Windows, Python 3.12+, Node 22.18+ for tests)

1. Create/select the intended chat in ZCode's GUI. Use its existing workspace directory and
   `sess_...` ID (these are technical identifiers, not the game/project directory).
   If needed, inspect your local session metadata read-only; do not edit its index/database.
   Leave the model, tools and permission mode configured in the GUI as you want them.
2. Run prepare with explicit paths below. Choose **new private directories outside this clone**
   for `--output` and `--state-dir`. Paths/IDs below are placeholders, not literal values.
3. Close ZCode normally, preserving your chats. Install, then start ZCode normally again.
   The installer refuses a running ZCode; it does not kill processes or restart the model server.

```powershell
python experimental/desktop-live/patch.py prepare --asar "$env:LOCALAPPDATA\Programs\ZCode\resources\app.asar" --workspace "C:\path\to\.zcode\workspace\draft-ID" --session "sess_ID" --state-dir "C:\private\desktop-live-state" --output "C:\private\desktop-live-bundle"
python experimental/desktop-live/patch.py install --bundle "C:\private\desktop-live-bundle"
```

The bundle contains a generated **proprietary app archive** and its local backup. Keep the entire
bundle and runtime directory private; never upload either. On Windows, prepare removes inherited
directory access and grants the current user and SYSTEM access. The runtime generates an ephemeral
bearer token and a random loopback port in private `connection.json`; do not paste that file anywhere.
The patch does not disable any Electron protection. A build with enforced embedded integrity needs
official application support; this workaround does not bypass it.

## Use

Feed a JSON array of requests to `client.py --connection ...` on stdin. It reads the token locally
and never prints it. First enumerate windows, then attach using the intended returned window ID:

```powershell
'[{"action":"windows"}]' | python experimental/desktop-live/client.py --connection "C:\private\desktop-live-state\connection.json"
'[{"action":"attach","windowId":1}]' | python experimental/desktop-live/client.py --connection "C:\private\desktop-live-state\connection.json"
```

Use the **returned attachmentId** below; `ATTACHMENT` is a placeholder. Send only when the chat is idle.
Use a stable unique commandId when retrying a send whose response was lost, so the desktop can deduplicate it.

```json
[
  {"action":"send","attachmentId":"ATTACHMENT","commandId":"unique-check-1","text":"Reply with a short connectivity acknowledgment. Do not use tools or modify files."},
  {"action":"call","attachmentId":"ATTACHMENT","method":"conversationRowsRangeV4","args":{"sessionId":"sess_ID","limit":10}}
]
```

Send returns an acceptance acknowledgment, **not completion**. Poll rows for the completed visible
assistantText response. Page older rows with `beforeRowId` (use the returned row IDs), up to 30 rows
per query. Tool rows contain activity/results. Hidden reasoning and unknown row kinds are filtered;
pages can therefore be empty. `events` with `afterSequence` returns only bounded sequence markers,
not raw model frames. `getSessionLifecycle` is available but a ready backend does not prove a turn is idle.
Use `detach` with the attachmentId when finished. Reattach after ZCode restarts.

Workspace/session are pinned at prepare time; raw RPC methods and path overrides are rejected.
HTTP requests with an Origin header are rejected. This is not an OS sandbox: any program running
as your user with access to the token can send prompts with the GUI's current permissions.
Do not expose the port through tunnels or proxies. Coordinate all writers yourself: the standard
Bridge's scheduling locks do not cover this independent adapter. Do not run both against the same project.
Cancel/steer/approvals/model selection stay in the GUI; this helper does not silently approve them.

## Rollback and validation

Close ZCode normally, then:

```powershell
python experimental/desktop-live/patch.py rollback --bundle "C:\private\desktop-live-bundle"
```

Rollback verifies both hashes, restores only the original archive, and leaves chat databases alone.
It refuses to overwrite an application update. Stop using the old connection file after rollback.
If ZCode updates, use the official updated application and wait for a separately verified adapter;
do not edit the supported hash to force installation.

```powershell
node experimental/desktop-live/test-adapter.mjs
python -m unittest discover -s experimental/desktop-live -p test_patch.py
```

These tests use a fake host and synthetic ASAR; they do not contact a model or touch an installation.
The public generalized installer has been staged against the supported original locally, while the
running proof uses the same adapter architecture from the earlier local install. No cross-build or
fresh-machine certification is claimed. See [design decision](../../docs/decisions/ADR-010-experimental-desktop-live.md).
