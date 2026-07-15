# Storarr

A disk fills up. Most of it is movies you watched once and forgot about.
Storarr quietly trims the oldest-watched, stale-enough titles from Radarr
once your drive actually gets tight — and leaves everything alone the rest
of the time. One page of settings, no rule-builder to learn.

Built for people with a fixed-size drive and fast internet: storage is cheap
to refill, so there's no reason to hoard.

## How it works

- Runs a background check every N minutes.
- Does **nothing** unless your drive crosses a limit you set — either
  "used space ≥ X GB" or "free space ≤ X GB."
- Once triggered: asks Plex for movies that are watched and haven't been
  touched in `stale_days`, oldest-watched first, and deletes them via Radarr
  (up to a per-run safety cap) — rechecking your limits after each one, so
  it stops the moment you're clear.
- Deletes the full Radarr record, not just the file, so re-requesting the
  same movie later in Overseerr/Jellyseerr looks like a brand new request.
- Never touches unwatched movies/shows, recently-watched ones, or anything
  tagged with a "keep tag" you set — regardless of how full the drive gets.
- **TV shows via Sonarr are supported the same way as movies via Radarr**,
  with their own stale-days window and their own keep tag — just off by
  default, since most people want shows kept forever and movies rotating.
  Flip on "Also roll off stale shows" in Settings if that's not you.

## Install

```bash
git clone https://github.com/3spky5u-oss/storarr.git
cd storarr
docker compose up -d
```

That's the whole install. `docker-compose.yml` builds the image itself —
no registry, no manual build step. Then open `http://<host>:8585/settings`
and fill in:

- Plex URL + token
- Radarr URL + API key
- your thresholds

**Turn on Dry Run first.** It logs exactly what it would delete without
touching anything — check it once before trusting it for real.

Before deploying, edit the `/data-storage` volume mount in
`docker-compose.yml` to point at the same host path your Radarr container
already uses for the media library.

**Multiple disks / JBOD arrays** (e.g. an Unraid-style array without a
union filesystem): a single RAID/LVM/ZFS mount just works as-is since it's
one mount point. If your setup is several separate disks instead, mount
each one into the container and list them comma-separated in the "Storage
path(s)" setting — Storarr sums used/free space across all of them as one
pool.

### Finding your Plex token

Plex Web → open any item → "Get Info" → "View XML" → grab `X-Plex-Token`
from the URL.

### One gotcha

If your Plex container uses `network_mode: host`, other containers can't
reach it by name — use the host's LAN IP in the Plex URL setting instead
(e.g. `http://192.168.1.50:32400`).

## Settings

| Setting | What it does |
|---|---|
| Roll-off trigger (used GB) | Start evicting once used space reaches this |
| Minimum free space (GB) | Also start evicting if free space drops to this |
| Stale after (days, movies) | How long unwatched-since-last-view before a movie is eligible |
| Check interval (minutes) | How often the background loop checks |
| Max evictions per check | Safety cap per run, shared across movies+shows |
| Keep tag (movies) | A Radarr tag that's never evicted |
| Dry run | Log only, delete nothing |
| TV shows | Off by default; opt in for independent show rollover |
| Stale after (days, shows) | Same idea, separate window for shows once enabled |
| Keep tag (shows) | A Sonarr tag that's never evicted — independent of the movie keep tag |
| Admin password | Optional — set one if this is reachable beyond your LAN |

## Security note

The settings page holds your Plex token and Radarr API key in plaintext
(same as every other `*arr` app). Set an admin password in Settings if
this container is reachable outside your own network.

## For anyone pointing an agent at this repo

The whole app is one file (`app.py`, Flask, ~350 lines) plus four small
Jinja templates. No database, no migrations, no build step beyond `pip
install`. Config lives in `/data/config.json`, history in
`/data/history.json` — both plain JSON, safe to read or hand-edit. If
you're extending it, `evict_stale()` and `run_check()` in `app.py` are the
whole engine; everything else is UI around them.

## Why not Maintainerr / Tautulli scripts / etc.?

Those do more and are worth using if you want rule-builders, ratings-based
rules, or multi-condition logic. Storarr is deliberately narrow: one job,
one settings page.

## License

MIT — see `LICENSE`.
