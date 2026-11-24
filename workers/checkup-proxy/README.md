# checkup-proxy

Cloudflare Worker that fronts the Cloud Run service at
`checkup.jamapoonji.com` and caps how much traffic can reach it.

## Why it exists

Cloud Run is public and bills by request CPU time. `max-instances=1` bounds how
wide a flood can go, not how long it lasts. This Worker bounds it at the edge:

| Limit | Value | Then |
|---|---|---|
| Paths accepted | `GET /`, `GET /health`, `POST /api/schemes`, `POST /api/analyze` | 404 at the edge |
| Per IP | 30 requests / 60 seconds | 429 with `Retry-After: 60` |
| Global | 3000 requests / day | 429 with `Retry-After: 3600` |

## Why D1 and not KV

The first version used Workers KV. It looked fine and did nothing: KV is
eventually consistent, so a read immediately after a write returns the previous
value and the counter never climbs. 35 requests in a row all came back 200.

D1 is strongly consistent, and its free tier allows 100k row writes a day, which
the caps above stay inside. Two increments per request means the global cap of
3000/day writes about 6000 rows.

## Schema

```sql
CREATE TABLE IF NOT EXISTS hits (
  key TEXT PRIMARY KEY,
  n INTEGER NOT NULL,
  expires INTEGER NOT NULL
);
```

Keys are `ip:<address>:<minute-epoch>` and `day:<iso-date>`. Expired rows are
swept on roughly 1% of requests.

## Deploy

```bash
npx wrangler d1 create checkup-limits          # id goes into wrangler.toml
npx wrangler d1 execute checkup-limits --remote --command \
  "CREATE TABLE IF NOT EXISTS hits (key TEXT PRIMARY KEY, n INTEGER NOT NULL, expires INTEGER NOT NULL);"
npx wrangler deploy
```

`custom_domain = true` makes Cloudflare create the DNS record and certificate for
`checkup.jamapoonji.com`. No Google domain mapping and no Search Console
verification are involved.

## Changing a limit

Edit the constants in `index.js` and redeploy. Nothing in Google needs to change.
