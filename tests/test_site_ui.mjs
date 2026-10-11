import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { runBrowserScript, settle } from "./helpers/browser.mjs";

const source = fs.readFileSync(new URL("../site/app.js", import.meta.url), "utf8");
const groups = [1, 2].map((id) => ({
  id: `song-${id}`, songTitle: `Song ${id}`, artist: "Artist", entryCount: 1, channelCount: 1,
  channels: [{ id: `channel-${id}`, title: "Same Name", entryCount: 1 }],
}));
const ok = (payload) => ({ ok: true, async json() { return payload; } });

test("channel cards use stable IDs; folded songs do not fetch entries", async () => {
  const requests = [];
  const browser = runBrowserScript(source, { search: "?song=Song", fetch: async (url) => {
    requests.push(url);
    if (url === "/api/overview") return ok({ channels: [{ channel_id: "channel-1", channel_title: "Same Name" }] });
    if (url.startsWith("/api/search?")) return ok({ groups, total: 2 });
    return ok({ entries: [], total: 1 });
  } });
  await settle();
  assert.equal(browser.nodes.get("#channel-grid").children[0].href, "?channel=channel-1");
  assert.equal(requests.filter((url) => url.startsWith("/api/entries?")).length, 0);
  const song = browser.nodes.get("#results-list").children[0];
  song.open = true;
  await song.dispatch("toggle");
  await settle();
  assert.equal(requests.filter((url) => url.startsWith("/api/entries?")).length, 1);
  song.open = false;
  await song.dispatch("toggle");
  song.open = true;
  await song.dispatch("toggle");
  await settle();
  assert.equal(requests.filter((url) => url.startsWith("/api/entries?")).length, 1);
});

test("a one-page entry failure has a working retry button", async () => {
  let attempts = 0;
  const browser = runBrowserScript(source, { search: "?song=Song", fetch: async (url) => {
    if (url === "/api/overview") return ok({});
    if (url.startsWith("/api/search?")) return ok({ groups: groups.slice(0, 1), total: 1 });
    attempts += 1;
    if (attempts === 1) throw new Error("offline");
    return ok({ entries: [{ timestampText: "00:01", jumpUrl: "https://example.test" }], total: 1 });
  } });
  await settle();
  const song = browser.nodes.get("#results-list").children[0];
  const retry = song.find("entry-retry");
  assert.ok(retry, "failed entry requests must expose retry even without pagination");
  assert.equal(retry.hidden, false);
  await retry.dispatch("click");
  await settle();
  assert.equal(attempts, 2);
  assert.equal(retry.hidden, true);
  assert.ok(song.find("timestamp"));
});
