# Changelog

## 0.2.0 — 2026-09-14

- Records the provider's HTTP 403s. Some edges answer 403 to a few streams right after the
  exit address changes while `player_api.php` still answers 200, so the probe never sees
  them. From Dispatcharr 0.31.0, which writes its log to `/data/logs/dispatcharr.log`, the
  watcher follows that file and records a `forbidden` event every round with the count per
  channel. It never rotates on them. Check status sums them up, and the `started` event says
  whether the log was found.
- The README and the API key field say the key must belong to an admin: Dispatcharr leaves
  the account password out for anyone else. A failed rotation counts toward the cooldown
  and the hourly limit.
- The contract tests run the plugin's actions against a temporary runtime folder instead of
  the checkout. Tests, types, lint and build run in CI; `docs/MEMORY.md` holds the
  decisions, the deployment traps and the release routine.

## 0.1.1 — 2026-09-14

- A rotation no longer leaves the tunnel stopped. A stop request that timed out never sent
  the start, and a start refused three times left the tunnel down with every later probe
  timing out, which never counts. Now the start is always sent, and after a failed rotation
  the next round starts the tunnel if it is still stopped. A tunnel stopped by hand is left
  alone.
- The journal records whether Gluetun confirmed the stop.
- The watcher survives an unexpected error: it is recorded in the journal and Check status
  counts it. Before, anything but an API error stopped the watcher until the next channel
  started.
- The logo and the README changes made after 0.1.0 are in the release zip.
- Checked against Dispatcharr 0.31.0: nothing the plugin relies on changed.

## 0.1.0 — 2026-09-13

First release.

- Asks every active Xtream Codes account for its `player_api.php` every two minutes, with
  the account's user agent, at no cost in stream connections.
- Two probe rounds in a row in which any account answers between 520 and 527 rotate Gluetun
  onto another server through its control server, without recreating Gluetun or Dispatcharr.
- Records the old address, the new one and the provider's next answer in a journal.
- Guards: ten minutes between rotations, three an hour, and a tunnel that comes back on the
  same address counts as a failure. Answers such as 403, 507 or 509, and timeouts, never
  rotate.
- Ask the provider reports what each account answers right now without moving anything.
