// Protection dispatcher: a Cloudflare Worker whose cron trigger starts a live
// protection-monitor run through GitHub's workflow_dispatch API every 30
// minutes, because GitHub's own `schedule` drops most slots (ADR 0009,
// docs/research/0008). It only asks GitHub to run the workflow; the workflow
// keeps its concurrency group and its dry_run=true default for manual runs.
// Whether the level was met is judged independently by scripts/heartbeat.py.

const API = "https://api.github.com";
const ATTEMPTS = 2;
const RETRY_DELAY_MS = 5000;

// GitHub answers 204 (older API) or 200 with run details (current API).
const DISPATCHED = new Set([200, 204]);

// Every setting must be present and well-formed; a misconfigured dispatcher
// throws before any request rather than dispatching somewhere unexpected.
const CONFIG = {
  GH_DISPATCH_TOKEN: /^\S+$/,
  GITHUB_REPOSITORY: /^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/,
  WORKFLOW_FILE: /^[A-Za-z0-9._-]+\.ya?ml$/,
  WORKFLOW_REF: /^[A-Za-z0-9._\/-]+$/,
};

function checkConfig(env) {
  for (const [key, pattern] of Object.entries(CONFIG)) {
    const value = env[key];
    if (typeof value !== "string" || !pattern.test(value) || value.includes("..")) {
      // Never echo the value: one of these is the token.
      throw new Error(`dispatcher misconfigured: ${key} is missing or malformed`);
    }
  }
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export async function dispatchMonitor(env, { fetch = globalThis.fetch, sleep = wait } = {}) {
  checkConfig(env);
  const url = `${API}/repos/${env.GITHUB_REPOSITORY}/actions/workflows/${env.WORKFLOW_FILE}/dispatches`;
  const request = {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "trading-routine-protection-dispatcher",
      "Content-Type": "application/json",
    },
    // Live run: the external cron replaces the schedule, which is never a dry run.
    body: JSON.stringify({ ref: env.WORKFLOW_REF, inputs: { dry_run: "false" } }),
  };

  let failure;
  for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
    if (attempt > 1) await sleep(RETRY_DELAY_MS);
    let response;
    try {
      response = await fetch(url, request);
    } catch (err) {
      failure = err; // network error: transient, retry
      continue;
    }
    if (DISPATCHED.has(response.status)) {
      return { status: response.status, attempts: attempt };
    }
    const detail = (await response.text()).slice(0, 300);
    failure = new Error(`dispatch rejected: HTTP ${response.status} ${detail}`);
    if (response.status < 500) break; // bad token, scope or ref: retrying cannot help
  }
  throw failure;
}

export default {
  async scheduled(controller, env) {
    const { status, attempts } = await dispatchMonitor(env);
    console.log(`protection-monitor dispatched: HTTP ${status}, attempt ${attempts}`);
  },
};
