# Storarr

Disk-pressure-aware library rollover for Radarr/Sonarr + Plex.

Most cleanup tools work on a fixed timer: "delete anything watched more than
N days ago," whether your drive has 4TB free or 4GB. Storarr instead sits
completely quiet until your media drive actually gets tight, then trims the
oldest-watched, stale-enough titles — one at a time, rechecking after
each — until it's back under your line. If you've got room, nothing happens,
no matter how old a watched movie is.

Built for a home server with a fixed-size drive and a rotating movie library
("watch it once, it can go") sitting next to a TV library that should never
be touched.

## How it works

1. Runs a background check every N minutes (configurable).
2. If your storage path is under **both** limits — used space below the
   threshold, and free space above the floor — it does nothing.
3. Once either limit is breached, it asks Plex for movies that have been
   watched (`viewCount >= 1`) and last watched more than `stale_days` ago,
   oldest-watched first.
4. For each one (up to a per-run safety cap), it deletes the movie via the
   Radarr API — the full record, not just the file, with
   `addImportExclusion=false` — so if you request it again later in
   Overseerr/Jellyseerr it shows up as a fresh title, not a blocked re-add.
5. Rechecks your limits after every deletion and stops as soon as it's clear.
6. Never touches: TV shows (unless you explicitly opt in), unwatched movies,
   recently-watched movies, or anything tagged with your configured "keep tag."

TV show rollover is available but off by default — most people want shows
kept forever. Turn it on in Settings if you don't.

## Quick start

```bash
git clone <this-repo>
cd storarr
docker build -t storarr:latest .
```

Edit `docker-compose.example.yml` (rename to `docker-compose.yml`), pointing
the `/data-storage` mount at the same host path your Radarr/Sonarr already
use for your media library. Then:

```bash
docker compose up -d
```

Open `http://<host>:8585/settings` and fill in:

- Plex URL + token
- Radarr URL + API key
- (optional) Sonarr URL + API key, if you want TV rollover too
- Your thresholds

**Turn on Dry Run first.** It logs exactly what it would evict without
touching anything — a good way to sanity-check your settings before letting
it delete for real.

### Finding your Plex token

Any of the usual ways — easiest is opening a video in Plex Web, clicking
"Get Info" → "View XML," and grabbing the `X-Plex-Token` from the URL.

### A gotcha worth knowing

If your Plex container runs with `network_mode: host` (common), other
containers can't reach it by container name. Use the host's LAN IP in the
Plex URL setting instead (e.g. `http://192.168.1.50:32400`).

## Settings reference

| Setting | What it does |
|---|---|
| Roll-off trigger (disk used, GB) | Rollover starts once used space reaches this |
| Minimum free space (GB) | Rollover also starts if free space drops to this, whichever comes first |
| Stale after (days) | How long since last watched before a movie is eligible |
| Check interval (minutes) | How often the background loop checks |
| Max evictions per check | Safety cap — won't nuke your whole library in one pass if something's misconfigured |
| Keep tag | A Radarr/Sonarr tag that's never evicted, no matter how stale |
| Dry run | Logs what it would do, deletes nothing |
| TV shows | Off by default; enable to also roll off stale, fully-watched shows |

## Why not just use Maintainerr / Tautulli scripts / etc.?

Those are great and do more than Storarr. Storarr is intentionally narrow:
one job, one page of settings, no rule-builder to learn. If you want more
power (ratings, requester-based rules, collections), those tools are worth
using instead — or alongside it.

## License

MIT — see `LICENSE`.
