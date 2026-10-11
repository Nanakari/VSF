import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import worker from "../worker/index.js";
import { createMigratedDb } from "./helpers/worker_db.mjs";
import { exportContract } from "./helpers/export_contract.mjs";

test("Python exports and Worker search/entries share the artist contract", async (t) => {
  const db = await createMigratedDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const fixture = JSON.parse(fs.readFileSync(new URL("./fixtures/artist_contract.json", import.meta.url), "utf8"));
  const { manifest, tables } = exportContract("artists");
  async function post(route, payload) {
    const response = await worker.fetch(new Request(`https://artists.test/api/admin/${route}`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-seed-token": "test-token" },
      body: JSON.stringify(payload),
    }), env);
    assert.equal(response.status, 200, await response.text());
  }
  async function get(route, params) {
    const response = await worker.fetch(new Request(`https://artists.test/api/${route}?${new URLSearchParams(params)}`), env);
    assert.equal(response.status, 200);
    return response.json();
  }
  await post("snapshot/start", { version: manifest.version, tables: manifest.tables });
  for (const [table, rows] of Object.entries(tables)) {
    await post("seed", { version: manifest.version, table, rows });
  }
  await post("snapshot/commit", { version: manifest.version });

  for (const query of fixture.queries) {
    await t.test(query.artist, async () => {
      const matches = await get("search", { artist: query.artist });
      const expected = fixture.artists.filter((artist) => query.ids.includes(artist.id)).map((artist) => artist.title).sort();
      assert.deepEqual(matches.groups.map((group) => group.songTitle).sort(), expected);
      // Check every group, including rejected ones: /entries must not leak
      // rows that /search correctly filters out.
      for (const group of tables.song_groups) {
        const entries = await get("entries", { groupKey: group.group_key, artist: query.artist });
        assert.equal(entries.total, expected.includes(group.song_title) ? 1 : 0, group.song_title);
      }
    });
  }
});
