# Gluetun Rotate — working notes

Decisions, traps and the release routine. What the plugin does for a user is in the
[README](../README.md).

## Decisions

- **Rotate on 520-527**, Cloudflare's answers for an origin that refuses the exit address, two
  probe rounds in a row; **or on one source behind Cloudflare's block page** (0.4.0). Other 403s,
  507, 509 and timeouts never rotate: on the evidence of 12 September 2026 those were the
  provider failing with a good address.
- **The probe is `player_api.php`**, which costs no stream connection.
- **The rotation is Gluetun's `PUT /v1/vpn/status`** stopped then running, never a container
  restart. Tried live on 14 September 2026: 3.4 s, a new address. That address was refused; the
  watcher saw two 520 rounds and rotated again on its own, 3.5 minutes after the bad address.
- **403s are recorded**, from Dispatcharr's own log (`/data/logs/dispatcharr.log`, from
  Dispatcharr 0.31.0), per channel and per round. The probe cannot see them: on 13 September
  2026 some streams got 403 from the edge while `player_api.php` answered 200.
- **The block page is an address refused by one edge** (0.4.0). On 6 October 2026 the five US
  news channels all got 403: the provider sent the exit address `187.13.213.178` to
  `lanezegudive.lol`, which answered with Cloudflare's "Website Access Blocked" page, while from
  the house without the VPN, and from the VPN after a restart of Gluetun, the same sources
  answered 200 from `rusacuvoboru.lol`. The text of the page is the test, not the `cf-ray`
  header: every edge sits behind Cloudflare, so an origin's own 403 carries `cf-ray` too. The
  URL comes from the `Connection attempt N/3 for URL: … for channel <uuid>` line, which always
  precedes the channel's 403; it carries the account's credentials, so the journal records the
  feed and the edge only. The check reads at most 16 KB and closes a source that opens at once:
  a 403 costs no connection, an open source holds one for about 0.3 s.
- **A tunnel left stopped by a failed rotation is started again** on the next round. A tunnel
  stopped by hand is never touched.
- **Viewers hold the rotation back, with no time limit** (0.3.0, asked for by the operator on
  20 September 2026). A rotation drops every connection through the tunnel, and a stream that
  is still flowing when the probe is refused belongs to someone watching: cutting it to cure
  channels nobody is on is a bad trade. The test is `/proxy/ts/status`: `client_count > 0` and
  a source whose host is not local. The fallback card is served from `127.0.0.1`, so a channel
  sitting on it never holds the tunnel. A status that cannot be read does **not** hold it
  either: an unreachable Dispatcharr would otherwise block the cure for ever, and the watcher
  lives in the same container. **Measured on 7 October 2026**, when the operator asked to rotate
  under viewers only if the stream survives on its own: a probe viewer on Rai 1 through
  reservoarr went dry for 11.6 s, because the old TCP connection is never reset and reservoarr
  reconnects only after 25 s without data against a 12 s cushion; and the new address answered
  520 to every source, so the channel walked its chain and landed on the card. The hold stays.
- **A held-back rotation is journalled once per reason.** With no time limit the same line
  could repeat every two minutes for hours; the reason is remembered and written again only
  when it changes.

## Traps

- The API key must be an admin's: `/api/m3u/accounts/` leaves the password out for anyone else.
- The 403 line has two shapes: with the reservoarr profile `Stream process error for channel
  <uuid>: [delaybuf] upstream error HTTPError: HTTP Error 403`, with the built-in proxy
  `HTTP 403 from <url>`, without a uuid. The stream named in a `forbidden` event is the one the
  channel is on when the round reads it, which may not be the one that answered 403.
- Gluetun needs a role for this plugin in its auth file, with `GET /v1/publicip/ip`,
  `GET /v1/vpn/status` and `PUT /v1/vpn/status`. Its control server is `127.0.0.1:8000` from
  inside the shared network namespace.
- **The cooldown is 2 minutes** (0.4.0, chosen by the operator on 7 October 2026; 10 minutes
  before): a new address that is blocked too is replaced on the next round.
- A failed rotation counts toward the 2-minute cooldown and the 3-an-hour limit. Both survive
  a restart of the watcher (0.2.1): the last hour of rotations is kept in
  `.runtime/rotations.json` as wall-clock times and mapped onto the watcher's monotonic clock
  on its first round, not read from the journal, which is trimmed to 50 lines.
- Dispatcharr passes `params` to `run()`, never in `context`, and only the events in
  `apps/connect/models.py:SUPPORTED_EVENTS` reach a plugin (19 in 0.31.0).
- `process.py`, `journal.py`, `state.py` and `tailer.py` are copies of Underfed's: every zip has
  to stand on its own. A fix in one belongs in both.
- Importing a zip with `overwrite=true` replaces the folder, `.runtime/` included: copy it out
  and back. Reload after the import, then Apply.

## Release

1. Version in `plugin.json`, `gluetun_rotate/constants.py` and `pyproject.toml`.
2. A `CHANGELOG.md` section, written before the tag.
3. `python scripts/build_zip.py`, then an annotated tag `vX.Y.Z` named `Gluetun Rotate X.Y.Z`.
4. A GitHub Release with the CHANGELOG text, the list of commits it contains, and the zip.
5. Publishing the Release starts `.github/workflows/registry-pr.yml`, which opens the PR to
   `Dispatcharr/Plugins` from the `PilaScat/Plugins` fork: the version in
   `plugins/gluetun-rotate/plugin.json`, the README next to it when it changed, and the
   CHANGELOG section as the description. It needs the `REGISTRY_PR_TOKEN` secret, a classic PAT
   of PilaScat with `public_repo` only; it can be rerun by hand with the tag. The registry
   installs the zip at `source_url`, so a README change reaches users only with a new version.
