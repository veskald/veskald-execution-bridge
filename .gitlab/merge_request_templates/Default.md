<!--
The MR title becomes a line in the next release's What's Changed section.

Format (Conventional Commits):
  type: Subject in imperative mood, capitalized

Allowed types:
  feat      new user-facing capability
  fix       bug fix
  perf      performance improvement
  refactor  code restructure with no behaviour change
  docs      documentation only
  test      tests only
  build     build system / packaging (Docker, PyInstaller, deps)
  ci        CI workflows
  chore     misc maintenance (version bumps, lint config, ...)
  revert    revert a previous MR

Examples:
  feat: Add Bybit testnet toggle in settings dialog
  fix: Reconnect socket after MACHINE token rotation
  perf: Cache broker position-mode lookups across requests
  docs: Document AppImage installer bundle layout
  chore: Bump pybit to 5.16.0

The "mr-title" CI check enforces this format — bad titles block merge.
-->

## Summary

<!-- One or two sentences: what changed and why. -->

## Test plan

<!--
Bullet list of how you verified this:
- [ ] Smoke-tested the client against testnet
- [ ] Built the desktop app and re-ran the broker health check
- [ ] Docker image still healthy after 10 min idle
-->

## Notes for the reviewer

<!-- Optional: anything non-obvious, follow-ups, decisions deferred. -->
