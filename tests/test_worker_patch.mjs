import assert from "node:assert/strict";
import { test } from "node:test";

import worker from "../worker/index.js";
import { queryRows } from "./helpers/sqlite_d1.mjs";
import { createMigratedDb } from "./helpers/worker_db.mjs";
import { exportContract } from "./helpers/export_contract.mjs";

const TABLES = ["channels", "videos", "song_groups", "songs", "song_entries"];

function dataset(prefix, { invalidEntrySongId = null } = {}) {
  const channelId = `channel-${prefix}`;
  const videoId = `video-${prefix}`;
  const groupKey = `group-${prefix}`;
  const songId = Number(prefix.replace(/\D/g, "")) || 1;
  return {
    channels: [{ channel_id: channelId, channel_title: `Channel ${prefix}` }],
    videos: [{ video_id: videoId, channel_id: channelId, title: `Video ${prefix}`, published_at: "2025-01-01", url: `https://example.test/${videoId}`, indexed_at: "2025-01-01" }],
    song_groups: [{ group_key: groupKey, song_title: `Song ${prefix}`, artist: "Artist", title_search: `song ${prefix}`, artist_search: "artist", entry_count: 1, channel_count: 1 }],
    songs: [{ id: songId, channel_id: channelId, canonical_song_title: `Song ${prefix}`, normalized_song_title: `song ${prefix}`, artist: "Artist", group_key: groupKey, created_at: "2025-01-01", updated_at: "2025-01-01" }],
    song_entries: [{ id: songId, song_id: invalidEntrySongId ?? songId, group_key: groupKey, video_id: videoId, timestamp_text: "0:01", seconds: 1, raw_song_title: `Song ${prefix}`, normalized_song_title: `song ${prefix}`, source_comment: "", jump_url: `https://example.test/${videoId}#t=1`, created_at: "2025-01-01" }],
  };
}

function counts(rows) {
  return Object.fromEntries(TABLES.map((table) => [table, rows[table].length]));
}

async function call(env, path, payload) {
  const response = await worker.fetch(new Request(`https://patch.test${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-seed-token": "test-token" },
    body: JSON.stringify(payload),
  }), env);
  return { status: response.status, body: await response.json() };
}

async function fullImport(env, version, rows) {
  assert.equal((await call(env, "/api/admin/snapshot/start", { version, tables: counts(rows) })).status, 200);
  for (const table of TABLES) {
    const result = await call(env, "/api/admin/seed", { version, table, rows: rows[table] });
    assert.equal(result.status, 200, `${table} seed failed: ${JSON.stringify(result.body)}`);
  }
  assert.equal((await call(env, "/api/admin/snapshot/commit", { version })).status, 200);
}

async function liveIds(db) {
  const result = {};
  for (const table of TABLES) {
    const key = table === "channels" ? "channel_id"
      : table === "videos" ? "video_id"
        : table === "song_groups" ? "group_key" : "id";
    result[table] = (await queryRows(db, `SELECT ${key} FROM ${table} ORDER BY ${key}`)).map((row) => row[key]);
  }
  return result;
}

function changeCounts(rows, oldRows) {
  return Object.fromEntries(TABLES.map((table) => [table, {
    upserts: rows[table].length,
    deletes: oldRows[table].length,
  }]));
}

for (const scenario of ["promotion", "demotion"]) {
  test(`real exports preserve retained references during artist ${scenario}`, async (t) => {
    const db = await createMigratedDb();
    t.after(() => db.close());
    const env = { DB: db, SEED_TOKEN: "test-token" };
    const { before, after, diff } = exportContract(scenario);
    await fullImport(env, before.manifest.version, before.tables);
    assert.deepEqual(diff.song_groups.deletes, [scenario === "promotion" ? "king::" : "king::kanaria"]);
    assert.ok(!diff.songs.deletes.includes(1));
    assert.ok(!diff.song_entries.deletes.includes(1));

    const version = after.manifest.version;
    const changes = Object.fromEntries(TABLES.map((table) => [table, {
      upserts: diff[table].upserts.length, deletes: diff[table].deletes.length,
    }]));
    assert.equal((await call(env, "/api/admin/patch/start", {
      version, base_version: before.manifest.version, tables: after.manifest.tables, changes,
    })).status, 200);
    for (const table of TABLES) {
      assert.equal((await call(env, "/api/admin/patch", { version, table, ...diff[table] })).status, 200);
    }
    assert.equal((await call(env, "/api/admin/patch/commit", { version })).status, 200);
    for (const table of TABLES) {
      const key = table === "channels" ? "channel_id" : table === "videos" ? "video_id"
        : table === "song_groups" ? "group_key" : "id";
      // Channel exports also contain overview counts; compare live keys and
      // compare all fields for the rows whose foreign keys were reassigned.
      assert.deepEqual((await queryRows(db, `SELECT ${key} FROM ${table} ORDER BY ${key}`)).map((row) => row[key]),
        after.tables[table].map((row) => row[key]).sort());
    }
    assert.deepEqual(await queryRows(db, "SELECT * FROM songs ORDER BY id"), after.tables.songs);
    assert.deepEqual(await queryRows(db, "SELECT * FROM song_entries ORDER BY id"), after.tables.song_entries);
    assert.deepEqual(await queryRows(db, "PRAGMA foreign_key_check"), []);
    assert.equal((await queryRows(db, "PRAGMA foreign_keys"))[0].foreign_keys, 1);
    assert.equal((await queryRows(db, "PRAGMA defer_foreign_keys"))[0].defer_foreign_keys, 0);
    assert.equal((await call(env, "/api/admin/patch/commit", { version })).status, 200);
  });
}

test("incremental patch applies row updates and dependency-safe deletes atomically", async (t) => {
  const db = await createMigratedDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  await fullImport(env, "old", oldRows);

  assert.equal((await call(env, "/api/admin/patch/start", {
    version: "new",
    base_version: "old",
    tables: counts(newRows),
    changes: changeCounts(newRows, oldRows),
  })).status, 200);
  for (const table of TABLES) {
    const result = await call(env, "/api/admin/patch", {
      version: "new",
      table,
      upserts: newRows[table],
      deletes: oldRows[table].map((row) => row[table === "channels" ? "channel_id" : table === "videos" ? "video_id" : table === "song_groups" ? "group_key" : "id"]),
    });
    assert.equal(result.status, 200, `${table} patch failed: ${JSON.stringify(result.body)}`);
  }

  assert.deepEqual(await call(env, "/api/admin/patch/commit", { version: "new" }), {
    status: 200,
    body: { ok: true, version: "new", status: "ready" },
  });
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-2"],
    videos: ["video-2"],
    song_groups: ["group-2"],
    songs: [2],
    song_entries: [2],
  });
  assert.deepEqual(await queryRows(db, "SELECT version, status FROM dataset_meta WHERE id = 1"), [
    { version: "new", status: "ready" },
  ]);
});

test("an incomplete or stale patch leaves the live dataset unchanged", async (t) => {
  const db = await createMigratedDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  await fullImport(env, "old", oldRows);

  assert.equal((await call(env, "/api/admin/patch/start", {
    version: "incomplete",
    base_version: "old",
    tables: counts(newRows),
    changes: changeCounts(newRows, oldRows),
  })).status, 200);
  assert.equal((await call(env, "/api/admin/patch/commit", { version: "incomplete" })).status, 409);
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-1"],
    videos: ["video-1"],
    song_groups: ["group-1"],
    songs: [1],
    song_entries: [1],
  });

  const stale = await call(env, "/api/admin/patch/start", {
    version: "stale",
    base_version: "not-current",
    tables: counts(newRows),
    changes: changeCounts(newRows, oldRows),
  });
  assert.equal(stale.status, 409);
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-1"],
    videos: ["video-1"],
    song_groups: ["group-1"],
    songs: [1],
    song_entries: [1],
  });
});

test("a failed patch commit rolls back every live table", async (t) => {
  const db = await createMigratedDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const rows = dataset("1");
  await fullImport(env, "old", rows);
  const before = {};
  for (const table of [...TABLES, "dataset_meta"]) {
    before[table] = await queryRows(db, `SELECT * FROM ${table}`);
  }

  assert.equal((await call(env, "/api/admin/patch/start", {
    version: "broken",
    base_version: "old",
    tables: counts(rows),
    changes: {
      channels: { upserts: 0, deletes: 0 },
      videos: { upserts: 0, deletes: 0 },
      song_groups: { upserts: 0, deletes: 0 },
      songs: { upserts: 0, deletes: 0 },
      song_entries: { upserts: 1, deletes: 0 },
    },
  })).status, 200);
  const invalidEntry = { ...rows.song_entries[0], song_id: 99999 };
  assert.equal((await call(env, "/api/admin/patch", {
    version: "broken",
    table: "song_entries",
    upserts: [invalidEntry],
    deletes: [],
  })).status, 200);

  assert.equal((await call(env, "/api/admin/patch/commit", { version: "broken" })).status, 500);
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-1"],
    videos: ["video-1"],
    song_groups: ["group-1"],
    songs: [1],
    song_entries: [1],
  });
  assert.deepEqual(await queryRows(db, "SELECT song_id FROM song_entries"), [{ song_id: 1 }]);
  for (const table of [...TABLES, "dataset_meta"]) {
    assert.deepEqual(await queryRows(db, `SELECT * FROM ${table}`), before[table]);
  }
  assert.equal((await queryRows(db, "PRAGMA defer_foreign_keys"))[0].defer_foreign_keys, 0);
  assert.deepEqual(await queryRows(db, "PRAGMA foreign_key_check"), []);
});
