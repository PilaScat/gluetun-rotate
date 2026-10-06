# Changelog

## 0.4.0 — 2026-10-07

- **A source behind Cloudflare's block page rotates the tunnel in one round.** The provider
  sends each exit address to an edge of its choosing, and on 6 October 2026 the edge given to
  one address answered the five US news sources with Cloudflare's "Website Access Blocked"
  page, while `player_api.php` and the other edges still answered: the probe saw nothing and
  the channels stayed on their fallback. From the same server without the VPN, and from the VPN
  after a new address, the same sources answered 200. For a 403 in the Dispatcharr log the
  watcher now asks for the URL the channel was trying, reading at most 16 KB and closing at
  once a source that opens; the block page is journalled as `blocked`, with the feed and the
  edge, and the tunnel rotates without waiting for a second round. The source is asked again
  every round until it opens (`unblocked`), so a new address that is blocked too is replaced
  as well. Any other 403 is still only recorded.
- **Two minutes between rotations**, down from ten, so that second replacement comes on the
  next round. The limit of three an hour stays.
- Viewers still hold every rotation back. Measured on 7 October with a probe viewer through
  reservoarr: the stream went dry for 11.6 s, because the old connection is never reset and
  reservoarr reconnects only after 25 s without data, and the new address was refused with
  520, which sent the channel to its fallback.

## 0.3.0 — 2026-09-20

- **A rotation waits for the last viewer.** Rotating drops every connection through the
  tunnel, so anyone watching a channel from the provider lost their stream even though it
  was working. The watcher now reads `/proxy/ts/status` before it rotates and holds back
  while a channel has viewers on a source that is not local: the fallback card served from
  `127.0.0.1` does not count, because nothing is flowing from the provider there anyway. It
  rotates on the first round after the last of them leaves. There is no time limit: an
  address the provider refuses is of no use to anyone but the people already watching.
- A held-back rotation is written to the journal **once per reason**, not every round, so a
  long wait no longer fills it with the same line.

## 0.2.1 — 2026-09-14

- The 10-minute cooldown and the limit of 3 rotations an hour hold across a restart of the
  watcher. The rotations of the last hour lived only in memory, so an Apply, a plugin reload
  or a restart of Dispatcharr let the watcher rotate again at once. They are now kept in
  `.runtime/rotations.json` and read back on the watcher's first round. The review of the
  registry submission found it.
- README: a manual install unzips the release into `/data/plugins`, since the archive holds
  the `gluetun-rotate` folder; Check status reports how many rounds had HTTP 403s and the
  counts of the last one, not a sum; a rotation also drops the streams of an account that
  still answers.

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
