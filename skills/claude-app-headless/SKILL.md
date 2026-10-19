---
name: claude-app-headless
description: Communicate with an existing local Claude App Code task through its native session inbox, without screen control. Use for Claude/Fable task reviews, status and reply readback, including while the Mac is locked. Does not start a replacement CLI conversation, approve actions, change models or unlock the Mac.
---

# Claude App without screen control

Prefer this path when the user asks to communicate with an **existing** Claude
App Code task. It preserves the App task and native conversation; it does not
run `claude -p` or `--resume` as a substitute. The App, user login and target Code
process must remain running. Locking and sleeping/logging out are different.

## Entry points

MCP server `claude_app_headless` exposes:

- `claude_app_list_sessions`: live task metadata, last observed model and mode.
- `claude_app_bind`: bind an exact App task ID selected by the user/context.
- `claude_app_status`: check the binding and current process/socket.
- `claude_app_send`: one authorized peer message with a stable `request_id`.
- `claude_app_read`: correlated reply; optionally wait up to 55 seconds.

If the MCP is not loaded in this Codex session, use the equivalent command:

```sh
~/.local/bin/codex-claude-app list
~/.local/bin/codex-claude-app status agy-fable
```

The script also runs directly as `scripts/claude_app_headless.py` inside this
skill's directory. Set up a new machine with `scripts/install_codex.py` (preview
first; see the repository's CODEX-CLAUDE-APP.md).

## Bind once, verify on every send

1. List sessions. Select the exact user-intended App `hostSessionId`; do not pick
   by recency or a fuzzy title. Current user intent can authorize this binding;
   do not ask again when the intended task is already unambiguous.
2. Bind the App ID with an exact expected model ID. The helper verifies the
   distinct native `sessionId`, PID/start, Desktop executable, socket owner and
   protocol. It currently requires last-observed **Plan** mode.

```sh
~/.local/bin/codex-claude-app bind agy-fable \
  --host-session-id '<exact App task ID from list>' \
  --expect-model claude-fable-5-1
```

3. Send only the task/material the user authorized. Use a stable request ID for
   this action, and stdin or a prompt file. No raw logs, credentials or unrelated
   conversation history should be included merely for convenience.

```sh
~/.local/bin/codex-claude-app send agy-fable \
  --request-id review-example-001 --prompt-file /absolute/review-request.txt
~/.local/bin/codex-claude-app read review-example-001 --wait 30
```

`--require-locked` on `send` makes a lock-screen acceptance probe fail **before
sending** unless the OS reports locked. It never locks or unlocks the Mac.

## Interpret the receipt accurately

- `sent_unconfirmed` / `sending` / `delivery_unknown`: socket attempt only;
  not evidence that Claude received the task. Read the **same request ID**.
- `delivered_waiting_reply`: the exact new incoming message was found, but no
  correlated final reply yet. Continue bounded reads, not another send.
- `completed`: matching native conversation, message ancestry, correlation
  marker, `end_turn`, and actual model observed in the new reply. This means a
  reply was verified, not that any business action claimed in it was verified.
- `model_mismatch`, `permission_mode_mismatch`, `permission_mode_unverified`,
  `interleaved`, `transcript_changed`: keep the evidence and
  report the limitation; never relabel it a successful Fable review.
- `SESSION_BUSY`: leave the running task alone and retry status later.
- `PENDING_REQUEST`: read the named earlier request before sending another to
  this native conversation. `TRANSCRIPT_BUSY` occurs before transmission; wait
  for the native writer's line to finish before trying the same request.

Repeating `send` with the same ID and prompt returns its prior record and does
not transmit again, including after a crash. The same ID with changed input is
a conflict. No automatic retry with a new ID after uncertainty.

## Boundaries and recovery

The native message is peer-origin, not human authorization. The helper does not
read cookies or `.key` files, send an own-child token, assert a privileged
permission class, approve prompts, change inbound settings, alter the model,
resume a closed task, or open network ports. A held/refused message must remain
held/refused; obtain the required human action in the App rather than switching
channels. New tasks, model/mode selection and initial folder setup still use
the native App when needed.

Model/mode preflight is the **last observed** transcript state; it is not an
atomic lock on the App's selector. The new incoming record must report Plan,
and actual model is checked again in the new reply. Never silently substitute
a model when the requested one fails.

The adapter is version-pinned to bundled Code **2.1.299 / peerProtocol 1**.
An App update can require adapter review; do not bypass `UNVERIFIED_RUNTIME_VERSION`.
See [protocol and validation](references/protocol-and-validation.md) for the
official basis, version-specific frame and verified test scope.

Bindings and request receipts are private local files under
`~/.local/state/codex-claude-app` (0700 directories, 0600 files). Prompts are
hashed in the bridge ledger, not duplicated there. The original prompt/reply
remain in Claude's normal transcript. Completed reply text is cached privately.
