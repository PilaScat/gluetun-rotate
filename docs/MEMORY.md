# Gluetun Rotate — working notes

Decisions, traps and the release routine. What the plugin does for a user is in the
[README](../README.md).

## Decisions

- **Rotate only on 520-527**, Cloudflare's answers for an origin that refuses the exit
  address, two probe rounds in a row. 403, 507, 509 and timeouts never rotate: on the evidence
  of 12 September 2026 those were the provider failing with a good address.
- **The probe is `player_api.php`**, which costs no stream connection.
- **The rotation is Gluetun's `PUT /v1/vpn/status`** stopped then running, never a container
  restart. Tried live on 14 September 2026: 3.4 s, a new address. That address was refused; the
  watcher saw two 520 rounds and rotated again on its own, 3.5 minutes after the bad address.
- **403s are only recorded**, from Dispatcharr's own log (`/data/logs/dispatcharr.log`, from
  Dispatcharr 0.31.0), per channel and per round. Whether a rotation would help them is for the
  journal to show.
- **A tunnel left stopped by a failed rotation is started again** on the next round. A tunnel
  stopped by hand is never touched.

## Traps

- The API key must be an admin's: `/api/m3u/accounts/` leaves the password out for anyone else.
- Gluetun needs a role for this plugin in its auth file, with `GET /v1/publicip/ip`,
  `GET /v1/vpn/status` and `PUT /v1/vpn/status`. Its control server is `127.0.0.1:8000` from
  inside the shared network namespace.
- A failed rotation counts toward the 10-minute cooldown and the 3-an-hour limit. Both survive
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
