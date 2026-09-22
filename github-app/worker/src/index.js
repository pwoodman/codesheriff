/**
 * The Code Sheriff GitHub App — webhook handler + web dashboard.
 * Keep event selection in sync with quality_gates.github_app.job_from_webhook.
 */

const CHECK_NAME = "The Code Sheriff";
const DISPATCH_EVENT = "the-codesheriff";
const USER_AGENT = "the-codesheriff";
const PULL_ACTIONS = new Set([
  "opened",
  "synchronize",
  "reopened",
  "ready_for_review",
]);

const DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>The Code Sheriff</title>
<style>:root{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#e6edf3;--mt:#8b949e;--ac:#58a6ff;--gn:#3fb950;--rd:#f85149;--yl:#d29922}
@media(prefers-color-scheme:light){:root{--bg:#fff;--sf:#f6f8fa;--bd:#d0d7de;--tx:#1f2328;--mt:#656d76;--ac:#0969da;--gn:#1a7f37;--rd:#cf222e;--yl:#bf8700}}
*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--tx)}
.c{max-width:1200px;margin:0 auto;padding:2rem}header{border-bottom:1px solid var(--bd);padding-bottom:1rem;margin-bottom:2rem}
h1{font-size:1.5rem;display:flex;align-items:center;gap:.5rem}.b{background:var(--ac);color:#fff;padding:.15rem .5rem;border-radius:999px;font-size:.75rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1rem;margin-bottom:2rem}
.cd{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:1.25rem}
.cd h3{font-size:.85rem;color:var(--mt);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem}
.cd .v{font-size:2rem;font-weight:700}.v.gn{color:var(--gn)}.v.rd{color:var(--rd)}
table{width:100%;border-collapse:collapse;background:var(--sf);border:1px solid var(--bd);border-radius:8px;overflow:hidden}
th,td{padding:.75rem 1rem;text-align:left;border-bottom:1px solid var(--bd)}
th{background:var(--sf);font-weight:600;font-size:.85rem;color:var(--mt);text-transform:uppercase}tr:last-child td{border-bottom:none}
.pe{color:var(--rd)}.pw{color:var(--yl)}.sp{color:var(--gn)}.sf{color:var(--rd)}
.s2{margin-bottom:2rem}.s2 h2{font-size:1.1rem;margin-bottom:1rem}
.sf2{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:2rem;text-align:center}
.sf2 h2{margin-bottom:1rem}.sf2 p{color:var(--mt);margin-bottom:1.5rem;max-width:600px;margin-left:auto;margin-right:auto}
.btn{display:inline-block;background:var(--gn);color:#fff;padding:.75rem 2rem;border-radius:6px;text-decoration:none;font-weight:600;border:none;cursor:pointer;font-size:1rem}
.btn:hover{opacity:.9}.sts{display:flex;justify-content:center;gap:2rem;margin-top:2rem}.st{text-align:center}
.st .n{width:32px;height:32px;border-radius:50%;background:var(--ac);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:700;margin-bottom:.5rem}
.st .l{font-size:.85rem;color:var(--mt)}
.rl{list-style:none}.rl li{padding:.75rem 0;border-bottom:1px solid var(--bd);display:flex;justify-content:space-between;align-items:center}
.rl li:last-child{border-bottom:none}.rn{font-weight:600}.rs{font-size:.85rem}
.em{text-align:center;padding:3rem;color:var(--mt)}
@media(max-width:768px){.cards{grid-template-columns:1fr}.sts{flex-direction:column;align-items:center}}</style></head>
<body><div class="c"><header><h1>The Code Sheriff <span class="b">v1.18</span></h1></header>
<div id="sv" class="sf2"><h2>Protect your repositories in 2 clicks</h2>
<p>The Code Sheriff reviews every pull request for bugs, security issues, and code quality — before your team merges.</p>
<a id="ib" class="btn" href="#">Install on GitHub</a>
<div class="sts"><div class="st"><div class="n">1</div><div class="l">Click Install</div></div>
<div class="st"><div class="n">2</div><div class="l">Select repos</div></div>
<div class="st"><div class="n">3</div><div class="l">Reviews start automatically</div></div></div></div>
<div id="dv" style="display:none"><div class="cards">
<div class="cd"><h3>Status</h3><div id="ss" class="v">-</div></div>
<div class="cd"><h3>Reviews Today</h3><div id="sr" class="v">-</div></div>
<div class="cd"><h3>Findings</h3><div id="sf" class="v">-</div></div>
<div class="cd"><h3>Auto-Merge Ready</h3><div id="sm" class="v gn">-</div></div></div>
<div class="s2"><h2>Recent Reviews</h2><table><thead><tr><th>PR</th><th>Repo</th><th>Status</th><th>Findings</th><th>When</th></tr></thead>
<tbody id="rt"><tr><td colspan="5" class="em">Loading...</td></tr></tbody></table></div>
<div class="s2"><h2>Repositories</h2><ul id="rl" class="rl"><li class="em">Loading...</li></ul></div></div></div>
<script>
const A=window.location.origin;async function api(p){try{const r=await fetch(A+p);return r.ok?await r.json():null}catch{return null}}
async function init(){const h=await api('/health');if(h&&h.installed){document.getElementById('sv').style.display='none';document.getElementById('dv').style.display='block';ld()}else{document.getElementById('ib').href=h?.install_url||'#'}}
async function ld(){const[m,r,rp]=await Promise.all([api('/metrics'),api('/reviews'),api('/repos')]);
if(m){document.getElementById('ss').textContent=m.status||'OK';document.getElementById('sr').textContent=m.reviews_today||0;
document.getElementById('sf').textContent=m.total_findings||0;document.getElementById('sm').textContent=m.auto_merge_ready||0}
if(r&&r.length){document.getElementById('rt').innerHTML=r.map(x=>'<tr><td><a href="'+x.url+'" target="_blank">#'+x.pr+'</a></td><td>'+x.repo+'</td><td class="'+(x.status==='pass'?'sp':'sf')+'">'+x.status+'</td><td>'+x.findings_count+'</td><td>'+x.when+'</td></tr>').join('')}
else{document.getElementById('rt').innerHTML='<tr><td colspan="5" class="em">No reviews yet. Open a PR to get started.</td></tr>'}
if(rp&&rp.length){document.getElementById('rl').innerHTML=rp.map(x=>'<li><span class="rn">'+x.name+'</span><span class="rs">'+(x.enabled?'Active':'Paused')+'</span></li>').join('')}}
init();</script></body></html>`;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/") {
      return new Response(DASHBOARD_HTML, {
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }

    if (request.method === "GET" && url.pathname === "/health") {
      const installed = !!(env.GITHUB_TOKEN || env.DISPATCH_TOKEN);
      return json({
        ok: true,
        app: "the-codesheriff",
        installed,
        install_url: installed
          ? null
          : `https://github.com/apps/the-code-sheriff/installations/new`,
      });
    }

    if (request.method === "GET" && url.pathname === "/metrics") {
      return json(await getMetrics(env));
    }

    if (request.method === "GET" && url.pathname === "/reviews") {
      return json(await getReviews(env));
    }

    if (request.method === "GET" && url.pathname === "/repos") {
      return json(await getRepos(env));
    }

    if (request.method === "GET" && url.pathname === "/triage") {
      return json({ ok: true, message: "triage endpoint ready" });
    }

    if (request.method === "POST" && url.pathname === "/triage") {
      const body = await request.json();
      return json({ ok: true, action: body.action, finding_id: body.finding_id });
    }

    if (request.method !== "POST" || !["/", "/webhook", "/event"].includes(url.pathname)) {
      return json({ error: "not found" }, 404);
    }
    const secret = env.WEBHOOK_SECRET || env.QUALITY_APP_WEBHOOK_SECRET || "";
    const body = await request.arrayBuffer();
    const signature = request.headers.get("x-hub-signature-256");
    if (!(await verifySignature(secret, signature, body))) {
      return json({ error: "invalid signature" }, 401);
    }
    let payload;
    try {
      payload = JSON.parse(new TextDecoder().decode(body) || "{}");
    } catch {
      return json({ error: "invalid json" }, 400);
    }
    const event = request.headers.get("x-github-event") || "";
    const job = jobFromWebhook(event, payload);
    if (!job) {
      return json({ ok: true, ignored: event || "unknown" }, 202);
    }
    if (job.kind === "ping") {
      return json({ ok: true, pong: true });
    }
    if (job.kind === "installed") {
      return json({ ok: true, installed: job.account || "" });
    }
    const home = env.HOME_REPO || "pwoodman/the-code-sheriff";
    const handleHome = ["1", "true", "yes"].includes(
      String(env.QUALITY_APP_HANDLE_HOME || "").toLowerCase(),
    );
    if (!handleHome && job.repository === home) {
      return json({ ok: true, skipped: "home repository runs sheriff.yml" }, 202);
    }
    const token = env.DISPATCH_TOKEN || env.QUALITY_APP_DISPATCH_TOKEN || "";
    if (!token) {
      return json({ error: "DISPATCH_TOKEN is not set" }, 503);
    }
    const unsigned = {
      repository: job.repository,
      sha: job.sha,
      pr: job.pr,
      installation_id: job.installation_id,
      base: job.base,
      fork: job.fork,
    };
    if (job.command) unsigned.command = job.command;
    if (job.focus) unsigned.focus = job.focus;
    if (job.argument) unsigned.argument = job.argument;
    unsigned.sig = await signDispatch(secret, unsigned);
    const api = (env.GITHUB_API_URL || "https://api.github.com").replace(/\/$/, "");
    const response = await fetch(`${api}/repos/${home}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
      },
      body: JSON.stringify({ event_type: DISPATCH_EVENT, client_payload: unsigned }),
    });
    if (!response.ok) {
      const text = await response.text();
      return json({ error: "dispatch failed", github: text.slice(0, 300) }, 502);
    }
    return json({ ok: true, dispatched: unsigned.repository, pr: unsigned.pr }, 202);
  },
};

function jobFromWebhook(event, payload) {
  if (event === "ping") {
    return { kind: "ping" };
  }
  if (event === "installation" && payload.action === "created") {
    return { kind: "installed", account: payload.installation?.account?.login || "" };
  }
  if (event === "pull_request") {
    const pull = payload.pull_request || {};
    if (!PULL_ACTIONS.has(payload.action)) {
      return null;
    }
    if (pull.draft && payload.action !== "ready_for_review") {
      return null;
    }
    return runJob({
      repository: payload.repository?.full_name,
      sha: pull.head?.sha,
      pr: pull.number,
      installation_id: payload.installation?.id,
      base: pull.base?.ref,
      fork: isFork(pull, payload.repository?.full_name),
    });
  }
  if (event === "check_run" && payload.action === "rerequested") {
    const check = payload.check_run || {};
    if (check.name !== CHECK_NAME && check.name !== "quality-review") {
      return null;
    }
    const pull = (check.pull_requests || [])[0] || {};
    return runJob({
      repository: payload.repository?.full_name,
      sha: check.head_sha,
      pr: pull.number,
      installation_id: payload.installation?.id,
      base: pull.base?.ref,
      fork: "false",
    });
  }
  if (event === "check_suite" && ["requested", "rerequested"].includes(payload.action)) {
    const suite = payload.check_suite || {};
    const pull = (suite.pull_requests || [])[0] || {};
    return runJob({
      repository: payload.repository?.full_name,
      sha: suite.head_sha,
      pr: pull.number,
      installation_id: payload.installation?.id,
      base: pull.base?.ref,
      fork: "false",
      command: "review",
    });
  }
  if (event === "issue_comment" && ["created", "edited"].includes(payload.action)) {
    const issue = payload.issue || {};
    if (!issue.pull_request) {
      return null;
    }
    const parsed = parseSheriffCommand((payload.comment || {}).body || "");
    if (!parsed) {
      return null;
    }
    return runJob({
      repository: payload.repository?.full_name,
      sha: issue.pull_request.head?.sha || "HEAD",
      pr: issue.number,
      installation_id: payload.installation?.id,
      base: issue.pull_request.base?.ref,
      fork: "false",
      command: parsed.name,
      focus: parsed.focus,
      argument: parsed.argument,
    });
  }
  return null;
}

function parseSheriffCommand(body) {
  const match = String(body).match(/^\/sheriff(?:\s+([a-z-]+))?(?:\s+([\s\S]+))?$/im);
  if (!match) {
    return null;
  }
  const name = (match[1] || "help").toLowerCase();
  const allowed = new Set(["review", "summary", "explain", "check", "fix", "ignore", "help"]);
  if (!allowed.has(name)) {
    return { name: "help", focus: "", argument: name };
  }
  const rest = (match[2] || "").trim();
  if (name === "check") {
    const focus = rest.split(/\s+/)[0] || "security";
    return { name: "check", focus, argument: rest.slice(focus.length).trim() };
  }
  return { name, focus: "", argument: rest };
}

function isFork(pull, repository) {
  const headRepo = pull.head?.repo?.full_name;
  return headRepo && headRepo !== repository ? "true" : "false";
}

function runJob({ repository, sha, pr, installation_id, base, fork, command, focus, argument }) {
  if (!repository || !sha || !pr || !installation_id) {
    return null;
  }
  const job = {
    kind: "run",
    repository: String(repository),
    sha: String(sha),
    pr: String(pr),
    installation_id: String(installation_id),
    base: String(base || "main"),
    fork,
  };
  if (command) job.command = String(command);
  if (focus) job.focus = String(focus);
  if (argument) job.argument = String(argument);
  return job;
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function verifySignature(secret, header, body) {
  if (!secret || !header) {
    return false;
  }
  const hex = header.split("=")[1];
  if (!hex) {
    return false;
  }
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify("HMAC", key, hexToBytes(hex), body);
}

async function signDispatch(secret, payload) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const canonical = canonicalJson(payload);
  const sig = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(canonical),
  );
  return bytesToHex(new Uint8Array(sig));
}

function canonicalJson(payload) {
  return JSON.stringify(payload, Object.keys(payload).sort());
}

function hexToBytes(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

function bytesToHex(bytes) {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function getMetrics(env) {
  return {
    status: "OK",
    reviews_today: 0,
    total_findings: 0,
    auto_merge_ready: 0,
    uptime: Date.now(),
  };
}

async function getReviews(env) {
  return [];
}

async function getRepos(env) {
  return [];
}
