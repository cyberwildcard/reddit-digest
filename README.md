# reddit-digest

A personal, algorithm-free Reddit digest: pulls the top post per subreddit
from `config/subreddits.json`, daily for busy subreddits and weekly for
quieter ones, and publishes a single combined Atom feed via GitHub Pages.

No Reddit API credentials needed — Reddit's official Data API is
approval-gated (and was a dead end when tried), but the public
`/r/<sub>/top/.rss?t=day|week` endpoint works unauthenticated and survived
the 2026-05-30 shutdown of the unauthenticated `.json` endpoint.

## How it works

- `config/subreddits.json` — the subreddit list, each with a `cadence`
  (`"daily"` or `"weekly"`) and a `limit` (posts per run, default 1).
- `scripts/generate_feed.py` — fetches each subreddit's top/.rss, merges
  everything into one feed, writes `docs/feed.xml`.
- `.github/workflows/generate-feed.yml` — runs the script once a day via
  GitHub Actions, commits `docs/feed.xml` only if it actually changed.
- GitHub Pages serves `docs/` — the feed lives at the repo's Pages URL,
  `.../feed.xml`. Add that URL to Feedly (or any RSS reader).

Stateless by design: readers dedupe by entry GUID, so a weekly subreddit's
top-of-week post can be refetched every day without showing up more than
once to you — no local "already shown" tracking needed.

## Editing the subreddit list

Edit `config/subreddits.json` directly and push. No sync step, no re-auth —
it's just a plain list you maintain by hand.
