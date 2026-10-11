import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { Element, runBrowserScript, settle } from "./helpers/browser.mjs";

const source = fs.readFileSync(new URL("../static/setup.js", import.meta.url), "utf8");
const ok = (payload) => ({ ok: true, async json() { return payload; } });
class FormData extends Map {
  constructor(form) { super(Object.entries(form?.values || {})); }
  append(key, value) { this.set(key, value); }
}
function setup(fetch) {
  const root = new Element();
  root.dataset = { statusUrl: "/status", syncUrl: "/sync-site", saveConfigUrl: "/save-site-config" };
  const form = new Element("form");
  form.action = "/start";
  form.values = { max_videos: "3", reset_backfill: "on" };
  form.elements = { site_base_url: { value: "" }, site_seed_token: { value: "" } };
  const deletion = new Element("form");
  deletion.action = "/delete-channel";
  const remove = new Element("button");
  remove.dataset = { channelTitle: "Channel", channelId: "channel" };
  const backfill = new Element("button");
  backfill.dataset = { channelTitle: "Channel", channelId: "channel", mode: "backfill" };
  return runBrowserScript(source, { fetch, globals: { FormData }, nodes: new Map([
    ["#setup-root", root], ["#index-form", form], ["#delete-confirm-form", deletion],
    [".delete-channel-button", [remove]], [".update-channel-button", [backfill]],
  ]) });
}

test("locally completed deletion refreshes the channel list even when sync fails", async () => {
  let state = {};
  const browser = setup(async (url) => {
    if (url === "/status") return ok(state);
    assert.equal(url, "/delete-channel");
    state = { operation: "delete-channel", done: true, running: false, ok: false,
      local_changed: true, message: "已从本地删除，但站点同步失败" };
    return ok({ ok: true });
  });
  await settle();
  await browser.nodes.get(".delete-channel-button")[0].dispatch("click");
  browser.nodes.get("#delete-confirmation").value = "Channel";
  await browser.nodes.get("#delete-confirm-form").dispatch("submit");
  await settle();
  assert.equal(browser.nodes.get("#delete-dialog").open, false);
  assert.equal(browser.nodes.get("#confirm-delete-button").disabled, false);
  const reload = browser.timers.find(({ delay }) => delay === 1200);
  assert.ok(reload);
  reload.callback();
  assert.equal(browser.window.location.reloads, 1);
});

test("historical backfill uses the selected channel and preserves its saved cursor", async () => {
  const posts = [];
  const browser = setup(async (url, options) => {
    if (url === "/status") return ok({});
    posts.push({ url, payload: options.body });
    return ok({ ok: true });
  });
  await settle();
  await browser.nodes.get(".update-channel-button")[0].dispatch("click");
  await settle();
  assert.equal(posts[0].url, "/start");
  assert.equal(posts[0].payload.get("mode"), "backfill");
  assert.equal(posts[0].payload.get("channel"), "channel");
  assert.equal(posts[0].payload.get("max_videos"), "3");
  assert.equal(posts[0].payload.has("reset_backfill"), false);
  await browser.nodes.get("#sync-site-button").dispatch("click");
  await settle();
  assert.equal(posts[1].url, "/sync-site");
});

test("an old status response cannot unlock an in-flight job submission", async () => {
  let resolveStatus;
  let resolveStart;
  let firstStatus = true;
  const browser = setup(async (url) => {
    if (url === "/start") return new Promise((resolve) => { resolveStart = resolve; });
    if (firstStatus) {
      firstStatus = false;
      return new Promise((resolve) => { resolveStatus = resolve; });
    }
    return ok({ running: true, operation: "index" });
  });
  await browser.nodes.get("#index-form").dispatch("submit");
  resolveStatus(ok({ running: false, done: true, operation: "index" }));
  await settle();
  assert.equal(browser.nodes.get("#start-button").disabled, true);
  assert.equal(browser.timers.some(({ delay }) => delay === 1200), false);
  resolveStart(ok({ ok: true }));
  await settle();
  assert.equal(browser.nodes.get("#start-button").disabled, true);
});

test("status polling recovers after a transient failure", async () => {
  let attempts = 0;
  const browser = setup(async () => {
    attempts += 1;
    if (attempts === 1) throw new Error("offline");
    return ok({ message: "completed", running: false });
  });
  await settle();
  assert.match(browser.nodes.get("#status-message").textContent, /重试/);
  await browser.timers.find(({ delay }) => delay === 1500).callback();
  assert.equal(browser.nodes.get("#status-message").textContent, "completed");
});
