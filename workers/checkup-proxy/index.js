// Edge proxy for the mutual fund check-up.
//
// Cloud Run is the origin. This Worker exists for three reasons:
//   1. it serves checkup.jamapoonji.com with Cloudflare's certificate, without
//      needing Google domain mapping or a Search Console verification,
//   2. it caps request volume, so a bot cannot run up a Cloud Run bill,
//   3. it narrows the surface to the four paths the app actually serves.
//
// Counters live in D1, not KV. KV was the first attempt and it silently did
// nothing: KV is eventually consistent, so a read straight after a write returns
// the old value and the counter never climbs. D1 is strongly consistent and its
// free tier allows 100k row writes a day, which the caps below stay under.

const ORIGIN = "https://mf-checkup-152252833480.asia-south1.run.app";

const PER_IP_WINDOW_SECONDS = 60;
const PER_IP_MAX = 30;
const GLOBAL_DAILY_MAX = 3000;

const ALLOWED = [
  ["GET", "/"],
  ["POST", "/api/schemes"],
  ["POST", "/api/analyze"],
  ["GET", "/health"],
];

function allowed(method, path) {
  return ALLOWED.some(([m, p]) => m === method && p === path);
}

function clientIp(request) {
  return request.headers.get("cf-connecting-ip") || "unknown";
}

// One statement per key: insert or increment, and return the new count.
async function hit(env, key, ttlSeconds) {
  const expires = Math.floor(Date.now() / 1000) + ttlSeconds;
  const row = await env.DB.prepare(
    `INSERT INTO hits (key, n, expires) VALUES (?, 1, ?)
     ON CONFLICT(key) DO UPDATE SET n = n + 1
     RETURNING n`,
  )
    .bind(key, expires)
    .first();
  return row ? row.n : 1;
}

function limited(message, retryAfter) {
  return new Response(JSON.stringify({ error: message }), {
    status: 429,
    headers: {
      "content-type": "application/json",
      "cache-control": "no-store",
      "retry-after": String(retryAfter),
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (!allowed(request.method, url.pathname)) {
      return new Response(JSON.stringify({ error: "Not found" }), {
        status: 404,
        headers: { "content-type": "application/json", "cache-control": "no-store" },
      });
    }

    const now = Date.now();
    const minute = Math.floor(now / (PER_IP_WINDOW_SECONDS * 1000));
    const day = new Date(now).toISOString().slice(0, 10);

    if (env.DB) {
      const ipHits = await hit(env, `ip:${clientIp(request)}:${minute}`, PER_IP_WINDOW_SECONDS * 2);
      if (ipHits > PER_IP_MAX) {
        return limited("Too many requests. Please wait a minute and try again.", PER_IP_WINDOW_SECONDS);
      }

      const dayHits = await hit(env, `day:${day}`, 60 * 60 * 48);
      if (dayHits > GLOBAL_DAILY_MAX) {
        return limited("The check-up is busy today. Please try again tomorrow.", 3600);
      }

      // Cheap housekeeping: drop expired counters on a small fraction of requests.
      if (Math.random() < 0.01) {
        await env.DB.prepare("DELETE FROM hits WHERE expires < ?")
          .bind(Math.floor(now / 1000))
          .run();
      }
    }

    const target = new URL(url.pathname + url.search, ORIGIN);
    const proxied = new Request(target, request);
    const response = await fetch(proxied);

    const out = new Response(response.body, response);
    out.headers.set("x-checkup-proxy", "cloudflare");
    return out;
  },
};
