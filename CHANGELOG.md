# Changelog

## 0.1.0 — 2026-09-13

First release.

- Asks every active Xtream Codes account for its `player_api.php` every two minutes, with
  the account's user agent, at no cost in stream connections.
- Two answers in a row between 520 and 527 rotate Gluetun onto another server through its
  control server, without recreating Gluetun or Dispatcharr.
- Records the old address, the new one and the provider's next answer in a journal.
- Guards: ten minutes between rotations, three an hour, and a tunnel that comes back on the
  same address counts as a failure. Answers such as 403, 507 or 509, and timeouts, never
  rotate.
- Ask the provider reports what each account answers right now without moving anything.
