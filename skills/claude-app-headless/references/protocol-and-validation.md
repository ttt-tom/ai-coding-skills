# Protocol and validation

## Basis

- [Claude Code session inbox socket](https://code.claude.com/docs/en/cross-session-messaging#the-session-s-inbox-socket): scripts may post to a per-session Unix socket; native inbound controls still apply. On macOS the authentication line is optional.
- [Fable model configuration](https://code.claude.com/docs/en/model-config#work-with-fable): `claude-fable-5-1` is the exact model ID. Do not infer it from the unversioned `fable` alias.
- [Desktop sessions](https://code.claude.com/docs/en/desktop#work-across-sessions): Desktop task identity and terminal sessions are different surfaces.

Inspected 2026-10-19: Desktop bundled Code 2.1.299, `peerProtocol:1`.
`~/.claude/sessions/<pid>.json` supplies `entrypoint:claude-desktop`,
`hostSessionId`, native `sessionId`, `procStart`, version and inbox path.
The tested target's App/native IDs were matched to the existing user-selected
AGY task; actual values live only in the private local binding.

The complete message frame is not a public stable SDK contract. Static bundled
2.1.299 code was inspected: its inbox checks `session_id`, accepts `type:user`
with string `message.content`, retains `uuid`, and marks origin as a peer.
The helper uses that minimal frame, omits auth/from_mode/control/attachments,
and checks macOS `LOCAL_PEERPID` before writing. The native default/hold/refuse
decision is never rewritten. Future versions require explicit compatibility
review instead of assuming unchanged semantics.

Reply readback is from the exact native session's normal JSONL transcript.
Only records appended after this request's offset are considered; delivery
UUID, session ID, ancestry, marker, final text `end_turn`, and actual model
must match. Thinking blocks and unrelated replies are not returned.

## Validation scope

Author-written isolated tests use temporary metadata, Unix sockets and JSONL
fixtures. They cover exact task/model, duplicate requests across bridge restart,
unknown delivery, model mismatch, unrelated ancestry, interleaved human input,
busy session, native-ID drift, unsafe metadata/socket, private ledger and
transcript replacement. They do not invoke Claude or validate business effects.

Run:

```sh
python3 <skill-dir>/scripts/test_claude_app_headless.py
python3 <skill-dir>/scripts/claude_app_headless.py doctor
```

Real same-task transport and actual lock-screen acceptance are recorded in
`validation.json` here only after the corresponding checks are performed.
An unlocked socket round trip is not a locked-screen result. A locked test
records the OS lock state at send and at result readback; it does not assert
uninterrupted power, sleep or network availability between those observations.
