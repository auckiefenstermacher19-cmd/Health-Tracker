/**
 * Cloudflare Worker — GitHub API proxy for Habit Tracker
 *
 * This Worker is the ONLY place the GitHub Personal Access Token
 * exists. It is stored as a Cloudflare secret (set via the
 * dashboard or `wrangler secret put`), never committed to any
 * repo, never sent to the browser.
 *
 * The browser calls this Worker's URL instead of api.github.com
 * directly. The Worker attaches the real Authorization header
 * server-side and relays GitHub's response back.
 *
 * ── Environment variables / secrets required (set in Cloudflare) ──
 *   GITHUB_PAT     - the GitHub Personal Access Token (secret)
 *   GITHUB_OWNER   - your GitHub username (plain variable, not secret)
 *   GITHUB_REPO    - the repo name (plain variable, not secret)
 *   ALLOWED_ORIGIN - your GitHub Pages URL, e.g.
 *                    https://auckiefenstermacher19-cmd.github.io
 *                    (used for CORS; restricts which pages browsers let call
 *                    this Worker). Required: with it unset the Worker refuses
 *                    every request rather than falling back to '*'.
 *
 * ── Endpoints exposed to the app ──
 *   GET  /habits             -> returns { content, sha } for habits.csv
 *   PUT  /habits              body: { content, sha, message } -> writes habits.csv
 *   GET  /raw/definitions     -> returns habits/definitions.json as raw JSON text,
 *                                read through the same authenticated Contents
 *                                endpoint as /habits (so a private repo works)
 */

const GITHUB_API_BASE = 'https://api.github.com';

function corsHeaders(env) {
  // Fail closed: no ALLOWED_ORIGIN means no CORS header at all. fetch() rejects
  // the request before routing, so this branch should never be reached; '*'
  // would quietly let any page on the internet write habits.csv.
  return {
    'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, PUT, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function jsonResponse(data, status, env) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(env),
    },
  });
}

function textResponse(text, status, env) {
  return new Response(text, {
    status: status || 200,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      ...corsHeaders(env),
    },
  });
}

// The PUT side encodes with btoa(unescape(encodeURIComponent(content))), which
// packs each UTF-8 byte into its own char code. Plain atob() only undoes the
// base64 step and leaves those byte-per-char-code strings as mangled text, so
// any non-ASCII byte (accents, emoji, etc.) comes back corrupted. This helper
// undoes both steps: base64-decode to raw bytes, then UTF-8-decode those bytes.
function decodeBase64Utf8(b64) {
  const bin = atob(b64.replace(/\n/g, ''));
  const bytes = Uint8Array.from(bin, c => c.charCodeAt(0));
  return new TextDecoder('utf-8').decode(bytes);
}

async function githubFetch(env, path, options) {
  options = options || {};
  const url = GITHUB_API_BASE + path;
  const headers = Object.assign(
    {
      'Authorization': 'token ' + env.GITHUB_PAT,
      'Accept': 'application/vnd.github.v3+json',
      'User-Agent': 'habit-tracker-worker',
    },
    options.headers || {}
  );

  return fetch(url, {
    method: options.method || 'GET',
    headers,
    body: options.body,
  });
}

async function handleGetFile(env, filePath) {
  const res = await githubFetch(env, '/repos/' + env.GITHUB_OWNER + '/' + env.GITHUB_REPO + '/contents/' + filePath);

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return jsonResponse({ error: 'GitHub read failed', status: res.status, message: body.message }, res.status, env);
  }

  const json = await res.json();
  // Decode base64 content here on the server so the app gets plain text directly
  const decoded = decodeBase64Utf8(json.content);

  return jsonResponse({ content: decoded, sha: json.sha }, 200, env);
}

async function handlePutFile(env, filePath, requestBody) {
  let parsed;
  try {
    parsed = JSON.parse(requestBody);
  } catch (e) {
    return jsonResponse({ error: 'Invalid JSON body' }, 400, env);
  }

  const { content, sha, message } = parsed;

  if (typeof content !== 'string' || typeof sha !== 'string') {
    return jsonResponse({ error: 'content and sha are required' }, 400, env);
  }

  const encoded = btoa(unescape(encodeURIComponent(content)));

  const res = await githubFetch(env, '/repos/' + env.GITHUB_OWNER + '/' + env.GITHUB_REPO + '/contents/' + filePath, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: message || ('Update ' + filePath),
      content: encoded,
      sha: sha,
      branch: 'main',
    }),
  });

  const json = await res.json().catch(() => ({}));

  if (!res.ok) {
    return jsonResponse({ error: 'GitHub write failed', status: res.status, message: json.message }, res.status, env);
  }

  return jsonResponse({ success: true, sha: json.content ? json.content.sha : null }, 200, env);
}

async function handleRawFile(env, filePath) {
  // Raw passthrough using the same authenticated contents endpoint
  // (works even if the underlying repo is private, unlike
  // raw.githubusercontent.com which requires the repo to be public
  // for unauthenticated access).
  const res = await githubFetch(env, '/repos/' + env.GITHUB_OWNER + '/' + env.GITHUB_REPO + '/contents/' + filePath);

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return textResponse('ERROR: ' + (body.message || res.statusText), res.status, env);
  }

  const json = await res.json();
  const decoded = decodeBase64Utf8(json.content);

  return textResponse(decoded, 200, env);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // Fail closed. An unset ALLOWED_ORIGIN used to fall back to '*', which turns
    // a misconfigured deploy into a world-writable habits.csv. Refuse instead,
    // and send no CORS header, so the browser surfaces it as a CORS failure.
    if (!env.ALLOWED_ORIGIN) {
      return new Response(JSON.stringify({ error: 'ALLOWED_ORIGIN not configured' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // CORS preflight
    if (method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders(env) });
    }

    try {
      if (path === '/habits' && method === 'GET')  return await handleGetFile(env, 'habits.csv');
      if (path === '/habits' && method === 'PUT')  return await handlePutFile(env, 'habits.csv', await request.text());
      if (path === '/raw/definitions' && method === 'GET') return await handleRawFile(env, 'habits/definitions.json');
      return jsonResponse({ error: 'Not found', path }, 404, env);

    } catch (err) {
      return jsonResponse({ error: 'Worker exception', message: err.message }, 500, env);
    }
  },
};
