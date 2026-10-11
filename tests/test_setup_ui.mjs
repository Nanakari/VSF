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
  root.dataset = { statusUrl: "/status", syncUrl: "/sync-site", saveConfigUrl: "/save-site-config", channelsUrl: "/channels" };
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
    if (url === "/channels") return ok({ channels: [] });
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
  assert.equal(browser.nodes.get("#managed-channels").children[0].textContent, "当前数据库还没有频道。");
  assert.equal(browser.window.location.reloads, 0);
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

for (const succeeded of [true, false]) {
  test(`index completion preserves input without page reload (${succeeded ? "success" : "failure"})`, async () => {
    let state = {};
    const calls = [];
    const browser = setup(async (url) => {
      calls.push(url);
      if (url === "/start") {
        state = { operation: "index", done: true, running: false, ok: succeeded, local_changed: succeeded };
      }
      if (url === "/channels") return ok({ channels: [] });
      return ok(url === "/status" ? state : { ok: true });
    });
    await settle();
    const form = browser.nodes.get("#index-form");
    form.values = { channel: "@retry-me", max_videos: "2", max_comments: "7", recent_rescan_days: "0", include_all: "on" };
    await form.dispatch("submit");
    await settle();
    assert.equal(browser.timers.some(({ delay }) => delay === 1200), false, "must not discard form state by reloading");
    assert.equal(calls.includes("/channels"), succeeded);
    assert.deepEqual(form.values, { channel: "@retry-me", max_videos: "2", max_comments: "7", recent_rescan_days: "0", include_all: "on" });
  });
}

test("delete name error stays in the dialog through status polling and clears on correction", async () => {
  let posts = 0;
  const browser = setup(async (url) => {
    if (url !== "/status") posts += 1;
    return ok({ message: "previous job complete" });
  });
  await settle();
  await browser.nodes.get(".delete-channel-button")[0].dispatch("click");
  const input = browser.nodes.get("#delete-confirmation");
  input.value = "wrong";
  await browser.nodes.get("#delete-confirm-form").dispatch("submit");
  const error = browser.nodes.get("#delete-error");
  assert.ok(error && !error.hidden);
  assert.match(error.textContent, /名称不匹配/);
  await browser.timers.find(({ delay }) => delay === 1500).callback();
  assert.match(error.textContent, /名称不匹配/);
  assert.equal(posts, 0);
  input.value = "Channel";
  await input.dispatch("input");
  assert.equal(error.hidden, true);
});

test("newly refreshed channel buttons work and retain indexing limits", async () => {
  let state = {};
  const posts = [];
  const browser = setup(async (url, options) => {
    if (url === "/channels") return ok({ channels: [{ channel_id: "new", channel_title: "<New & Channel>", video_count: 2, song_count: 3, entry_count: 4 }] });
    if (url === "/start") {
      posts.push(options.body);
      state = { operation: "index", done: true, running: false, local_changed: true };
    }
    return ok(url === "/status" ? state : { ok: true });
  });
  await settle();
  await browser.nodes.get("#index-form").dispatch("submit");
  await settle();
  const card = browser.nodes.get("#managed-channels").children[0];
  assert.equal(card.children[0].children[0].textContent, "<New & Channel>");
  assert.equal(card.children[0].children[1].textContent, "2 个视频 · 3 首歌曲 · 4 个时间点");
  await card.children[1].children[0].dispatch("click");
  await settle();
  assert.equal(posts[1].get("channel"), "new");
  assert.equal(posts[1].get("mode"), "incremental");
  assert.equal(posts[1].get("max_videos"), "3");
  const newCard = browser.nodes.get("#managed-channels").children[0];
  await newCard.children[1].children[2].dispatch("click");
  assert.equal(browser.nodes.get("#delete-channel-id").value, "new");
  assert.match(browser.nodes.get("#delete-dialog-summary").textContent, /<New & Channel>.*2 个视频/);
});

test("failed channel refresh can be retried without losing input", async () => {
  let state = {};
  let attempts = 0;
  const browser = setup(async (url) => {
    if (url === "/channels") {
      if (++attempts === 1) throw new Error("offline");
      return ok({ channels: [] });
    }
    if (url === "/start") state = { operation: "index", done: true, local_changed: true };
    return ok(url === "/status" ? state : { ok: true });
  });
  await settle();
  await browser.nodes.get("#index-form").dispatch("submit");
  await settle();
  assert.equal(browser.nodes.get("#channel-list-error").hidden, false);
  assert.equal(browser.nodes.get("#retry-channels").hidden, false);
  await browser.nodes.get("#retry-channels").dispatch("click");
  await settle();
  assert.equal(browser.nodes.get("#channel-list-error").hidden, true);
  assert.equal(browser.nodes.get("#managed-channels").children[0].textContent, "当前数据库还没有频道。");
  assert.equal(browser.nodes.get("#index-form").values.max_videos, "3");
});

test("server deletion rejection is shown inside the dialog", async () => {
  const browser = setup(async (url) => url === "/delete-channel"
    ? { ok: false, async json() { return { message: "频道名称已变更" }; } }
    : ok({ message: "previous job complete" }));
  await settle();
  await browser.nodes.get(".delete-channel-button")[0].dispatch("click");
  browser.nodes.get("#delete-confirmation").value = "Channel";
  await browser.nodes.get("#delete-confirm-form").dispatch("submit");
  await settle();
  assert.equal(browser.nodes.get("#delete-dialog").open, true);
  assert.equal(browser.nodes.get("#delete-error").hidden, false);
  assert.equal(browser.nodes.get("#delete-error").textContent, "频道名称已变更");
});
