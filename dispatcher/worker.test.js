// Tests for the protection dispatcher (Cloudflare Worker). Run: node --test dispatcher/worker.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { dispatchMonitor } from "./worker.js";

const FAKE = "fake-credential-for-tests";
const ENV = Object.freeze({
  GH_DISPATCH_TOKEN: FAKE,
  GITHUB_REPOSITORY: "philipbergman6-glitch/TRADING-ROUTINE",
  WORKFLOW_FILE: "protection-monitor.yml",
  WORKFLOW_REF: "main",
});

// A fake GitHub: answers each call with the next scripted status (or throws
// it when it is an Error) and records every request it saw.
function fakeGitHub(...replies) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, init });
    const reply = replies[calls.length - 1];
    if (reply instanceof Error) throw reply;
    return new Response(reply === 204 ? null : "{}", { status: reply });
  };
  return { fetch, calls, sleep: async () => {} };
}

test("dispatches a live (dry_run=false) protection-monitor run on main", async () => {
  const gh = fakeGitHub(204);
  await dispatchMonitor(ENV, gh);
  assert.equal(gh.calls.length, 1);
  const { url, init } = gh.calls[0];
  assert.equal(url,
    "https://api.github.com/repos/philipbergman6-glitch/TRADING-ROUTINE/actions/workflows/protection-monitor.yml/dispatches");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, `Bearer ${FAKE}`);
  assert.equal(init.headers.Accept, "application/vnd.github+json");
  assert.equal(init.headers["X-GitHub-Api-Version"], "2022-11-28");
  assert.ok(init.headers["User-Agent"]);
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { dry_run: "false" } });
});

test("GitHub's 200 (run details) counts as dispatched", async () => {
  const gh = fakeGitHub(200);
  const result = await dispatchMonitor(ENV, gh);
  assert.equal(result.status, 200);
});

for (const status of [401, 403, 404, 422]) {
  test(`a ${status} rejection throws at once and never echoes the token`, async () => {
    const gh = fakeGitHub(status, 204);
    await assert.rejects(dispatchMonitor(ENV, gh), (err) => {
      assert.match(err.message, new RegExp(`HTTP ${status}`));
      assert.doesNotMatch(err.message, new RegExp(FAKE));
      return true;
    });
    assert.equal(gh.calls.length, 1, "a client error is not retried");
  });
}

test("a 5xx is retried once and then succeeds", async () => {
  const gh = fakeGitHub(502, 204);
  const result = await dispatchMonitor(ENV, gh);
  assert.deepEqual(result, { status: 204, attempts: 2 });
});

test("a network error is retried once and then succeeds", async () => {
  const gh = fakeGitHub(new TypeError("fetch failed"), 204);
  const result = await dispatchMonitor(ENV, gh);
  assert.equal(result.attempts, 2);
});

test("two failed attempts throw; nothing is dispatched silently", async () => {
  const gh = fakeGitHub(503, 503, 204);
  await assert.rejects(dispatchMonitor(ENV, gh), /HTTP 503/);
  assert.equal(gh.calls.length, 2);
});

test("two network errors throw the last one", async () => {
  const gh = fakeGitHub(new TypeError("fetch failed"), new TypeError("dns down"));
  await assert.rejects(dispatchMonitor(ENV, gh), /dns down/);
});

const BAD_CONFIG = [
  ["GH_DISPATCH_TOKEN", undefined],
  ["GH_DISPATCH_TOKEN", ""],
  ["GITHUB_REPOSITORY", "TRADING-ROUTINE"],
  ["GITHUB_REPOSITORY", "owner/repo/../x"],
  ["WORKFLOW_FILE", "protection-monitor"],
  ["WORKFLOW_FILE", "../tests.yml"],
  ["WORKFLOW_REF", ""],
];
for (const [key, value] of BAD_CONFIG) {
  test(`refuses ${key}=${JSON.stringify(value)} before any request`, async () => {
    const gh = fakeGitHub(204);
    await assert.rejects(dispatchMonitor({ ...ENV, [key]: value }, gh), new RegExp(key));
    assert.equal(gh.calls.length, 0);
  });
}

test("the cron handler dispatches through the platform fetch", async (t) => {
  const gh = fakeGitHub(204);
  t.mock.method(globalThis, "fetch", gh.fetch);
  await worker.scheduled({ cron: "0,30 13-20 * * MON-FRI" }, ENV, {});
  assert.equal(gh.calls.length, 1);
});

test("the cron handler throws so Cloudflare records a failed invocation", async (t) => {
  const gh = fakeGitHub(401);
  t.mock.method(globalThis, "fetch", gh.fetch);
  await assert.rejects(worker.scheduled({}, ENV, {}), /HTTP 401/);
});
