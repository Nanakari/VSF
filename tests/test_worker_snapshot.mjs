import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import worker from "../worker/index.js";
import { queryRows, SqliteD1 } from "./helpers/sqlite_d1.mjs";

const TABLES = {
  channels: "channels",
  videos: "videos",
  song_groups: "song_groups",
  songs: "songs",
  song_entries: "song_entries",
};

const EMPTY_COUNTS = {
  channels: 0,
  videos: 0,
  song_groups: 0,
  songs: 0,
  song_entries: 0,
};

async function createDb() {
  const db = new SqliteD1();
  await db.prepare("PRAGMA foreign_keys = ON").run();
  await db.batch([
    db.prepare("CREATE TABLE channels (channel_id TEXT PRIMARY KEY NOT NULL, channel_title TEXT NOT NULL)"),
    db.prepare("CREATE TABLE videos (video_id TEXT PRIMARY KEY NOT NULL, channel_id TEXT NOT NULL, title TEXT NOT NULL, published_at TEXT, url TEXT NOT NULL, indexed_at TEXT NOT NULL, FOREIGN KEY (channel_id) REFERENCES channels(channel_id))"),
    db.prepare("CREATE TABLE song_groups (group_key TEXT PRIMARY KEY NOT NULL, song_title TEXT NOT NULL, artist TEXT NOT NULL, title_search TEXT NOT NULL, artist_search TEXT NOT NULL, entry_count INTEGER NOT NULL, channel_count INTEGER NOT NULL)"),
    db.prepare("CREATE TABLE songs (id INTEGER PRIMARY KEY NOT NULL, channel_id TEXT NOT NULL, canonical_song_title TEXT NOT NULL, normalized_song_title TEXT NOT NULL, artist TEXT NOT NULL, group_key TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, FOREIGN KEY (channel_id) REFERENCES channels(channel_id), FOREIGN KEY (group_key) REFERENCES song_groups(group_key))"),
    db.prepare("CREATE TABLE song_entries (id INTEGER PRIMARY KEY NOT NULL, song_id INTEGER NOT NULL, group_key TEXT NOT NULL, video_id TEXT NOT NULL, timestamp_text TEXT NOT NULL, seconds INTEGER NOT NULL, raw_song_title TEXT NOT NULL, normalized_song_title TEXT NOT NULL, source_comment TEXT NOT NULL, jump_url TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY (song_id) REFERENCES songs(id), FOREIGN KEY (group_key) REFERENCES song_groups(group_key), FOREIGN KEY (video_id) REFERENCES videos(video_id))"),
  ]);
  return db;
}

async function createMigratedDb() {
  const db = new SqliteD1();
  await db.prepare("PRAGMA foreign_keys = ON").run();
  const migrationDir = new URL("../drizzle/", import.meta.url);
  const migrationFiles = fs.readdirSync(migrationDir)
    .filter((name) => name.endsWith(".sql"))
    .sort();
  for (const name of migrationFiles) {
    const migration = fs.readFileSync(new URL(name, migrationDir), "utf8");
    const statements = migration
      .split(/-->\s*statement-breakpoint/)
      .map((statement) => statement.trim())
      .filter(Boolean);
    for (const statement of statements) {
      await db.prepare(statement).run();
    }
  }
  return db;
}

function dataset(prefix, { invalidEntrySongId = null } = {}) {
  const channelId = `channel-${prefix}`;
  const videoId = `video-${prefix}`;
  const groupKey = `group-${prefix}`;
  const songId = Number(prefix.replace(/\D/g, "")) || 1;
  return {
    channels: [{ channel_id: channelId, channel_title: `Channel ${prefix}` }],
    videos: [{ video_id: videoId, channel_id: channelId, title: `Video ${prefix}`, published_at: "2025-01-01", url: `https://example.test/${videoId}`, indexed_at: "2025-01-01" }],
    song_groups: [{ group_key: groupKey, song_title: `Song ${prefix}`, artist: "Artist", title_search: `song ${prefix}`.toLocaleLowerCase(), artist_search: "artist", entry_count: 1, channel_count: 1 }],
    songs: [{ id: songId, channel_id: channelId, canonical_song_title: `Song ${prefix}`, normalized_song_title: `song ${prefix}`.toLocaleLowerCase(), artist: "Artist", group_key: groupKey, created_at: "2025-01-01", updated_at: "2025-01-01" }],
    song_entries: [{ id: songId, song_id: invalidEntrySongId ?? songId, group_key: groupKey, video_id: videoId, timestamp_text: "0:01", seconds: 1, raw_song_title: `Song ${prefix}`, normalized_song_title: `song ${prefix}`.toLocaleLowerCase(), source_comment: "", jump_url: `https://example.test/${videoId}#t=1`, created_at: "2025-01-01" }],
  };
}

function counts(rows) {
  return Object.fromEntries(Object.entries(rows).map(([table, values]) => [table, values.length]));
}

async function call(env, path, payload) {
  const response = await worker.fetch(new Request(`https://snapshot.test${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-seed-token": "test-token" },
    body: JSON.stringify(payload),
  }), env);
  return { status: response.status, body: await response.json() };
}

async function start(env, version, tableCounts) {
  return call(env, "/api/admin/snapshot/start", { version, tables: tableCounts });
}

async function seed(env, version, table, rows) {
  return call(env, "/api/admin/seed", { version, table, rows });
}

async function seedAll(env, version, rows) {
  for (const table of Object.keys(TABLES)) {
    const result = await seed(env, version, table, rows[table]);
    assert.equal(result.status, 200, `${table} seed failed: ${JSON.stringify(result.body)}`);
  }
}

async function commit(env, version) {
  return call(env, "/api/admin/snapshot/commit", { version });
}

test("sqlite bridge close waits for its child process to exit", async () => {
  const db = new SqliteD1();
  const child = db.child;
  await db.prepare("SELECT 1").run();
  await Promise.all([db.close(), db.close()]);
  assert.notEqual(child.exitCode, null);
  assert.equal(child.signalCode, null);
});

test("sqlite bridge close kills only an unresponsive child after a bounded wait", async () => {
  const db = new SqliteD1();
  const child = db.child;
  child.stdin.write = () => true;
  const startedAt = Date.now();
  await db.close();
  assert.ok(child.exitCode !== null || child.signalCode !== null);
  assert.ok(Date.now() - startedAt < 4500, "close exceeded its bounded cleanup timeout");
});

async function liveIds(db) {
  const result = {};
  for (const table of Object.keys(TABLES)) {
    const key = table === "channels" ? "channel_id"
      : table === "videos" ? "video_id"
        : table === "song_groups" ? "group_key" : "id";
    result[table] = (await queryRows(db, `SELECT ${key} FROM ${table} ORDER BY ${key}`)).map((row) => row[key]);
  }
  return result;
}

test("same-version start retry preserves staging rows and rejects count drift", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const rows = dataset("1");
  const expected = counts(rows);

  assert.equal((await start(env, "v1", expected)).status, 200);
  assert.equal((await seed(env, "v1", "channels", rows.channels)).status, 200);
  assert.deepEqual(await queryRows(db, "SELECT snapshot_version, channel_id FROM snapshot_channels_v2"), [
    { snapshot_version: "v1", channel_id: "channel-1" },
  ]);

  const retry = await start(env, "v1", expected);
  assert.deepEqual(retry, { status: 200, body: { ok: true, version: "v1", status: "loading" } });
  const drift = await start(env, "v1", { ...expected, channels: 2 });
  assert.equal(drift.status, 409);
  assert.equal((await queryRows(db, "SELECT COUNT(*) AS count FROM snapshot_channels_v2 WHERE snapshot_version = ?", "v1"))[0].count, 1);
});

test("a newer start removes superseded staging rows and a delayed old seed cannot restore them", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  assert.equal((await start(env, "old", counts(oldRows))).status, 200);
  await seedAll(env, "old", oldRows);

  let seedBatchPaused = false;
  let release;
  const releaseSignal = new Promise((resolve) => { release = resolve; });
  let resolvePaused;
  const seedStarted = new Promise((resolve) => { resolvePaused = resolve; });
  db.beforeBatch = async (statements) => {
    if (!seedBatchPaused && statements[0]?.sql.includes("UPDATE dataset_meta")) {
      seedBatchPaused = true;
      resolvePaused();
      await releaseSignal;
    }
  };
  const oldSeedPromise = seed(env, "old", "channels", oldRows.channels);
  await seedStarted;

  assert.equal((await start(env, "new", counts(newRows))).status, 200);
  db.beforeBatch = null;
  for (const table of Object.keys(TABLES)) {
    const stagingTable = `snapshot_${table}_v2`;
    assert.equal(
      (await queryRows(db, `SELECT COUNT(*) AS count FROM ${stagingTable} WHERE snapshot_version = ?`, "old"))[0].count,
      0,
      `${stagingTable} retained superseded rows`,
    );
  }

  release();
  assert.equal((await oldSeedPromise).status, 409);
  assert.equal((await queryRows(db, "SELECT COUNT(*) AS count FROM snapshot_channels_v2 WHERE snapshot_version = ?", "old"))[0].count, 0);
});

test("a delayed old seed cannot write after a newer start", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  assert.equal((await start(env, "old", counts(oldRows))).status, 200);

  let seedBatchPaused = false;
  let release;
  const releaseSignal = new Promise((resolve) => { release = resolve; });
  let resolvePaused;
  const seedStarted = new Promise((resolve) => { resolvePaused = resolve; });
  db.beforeBatch = async (statements) => {
    if (!seedBatchPaused && statements[0]?.sql.includes("UPDATE dataset_meta")) {
      seedBatchPaused = true;
      resolvePaused();
      await releaseSignal;
    }
  };
  const oldSeedPromise = seed(env, "old", "channels", oldRows.channels);
  await seedStarted;

  db.beforeBatch = null;
  assert.equal((await start(env, "new", counts(newRows))).status, 200);
  release();
  const oldSeed = await oldSeedPromise;
  assert.equal(oldSeed.status, 409);
  assert.equal((await queryRows(db, "SELECT COUNT(*) AS count FROM snapshot_channels_v2 WHERE snapshot_version = ?", "new"))[0].count, 0);

  assert.equal((await seed(env, "new", "channels", newRows.channels)).status, 200);
  const final = await commit(env, "new");
  assert.equal(final.status, 409, "the new snapshot is intentionally incomplete");
  assert.deepEqual(await liveIds(db), { channels: [], videos: [], song_groups: [], songs: [], song_entries: [] });
});

test("a delayed old commit cannot swap or damage the newer snapshot", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  assert.equal((await start(env, "old", counts(oldRows))).status, 200);
  await seedAll(env, "old", oldRows);

  let isPaused = false;
  let resolvePaused;
  const commitStarted = new Promise((resolve) => { resolvePaused = resolve; });
  let release;
  const releaseSignal = new Promise((resolve) => { release = resolve; });
  db.beforeBatch = async (statements) => {
    if (!isPaused && statements[0]?.sql.includes("SET status = 'committing'")) {
      isPaused = true;
      resolvePaused();
      await releaseSignal;
    }
  };
  const oldCommitPromise = commit(env, "old");
  await commitStarted;
  db.beforeBatch = null;

  assert.equal((await start(env, "new", counts(newRows))).status, 200);
  await seed(env, "new", "channels", newRows.channels);
  release();
  const oldCommit = await oldCommitPromise;
  assert.equal(oldCommit.status, 409);
  assert.equal((await queryRows(db, "SELECT COUNT(*) AS count FROM snapshot_channels_v2 WHERE snapshot_version = ?", "new"))[0].count, 1);
  assert.deepEqual(await liveIds(db), { channels: [], videos: [], song_groups: [], songs: [], song_entries: [] });
});

test("incomplete snapshot leaves live data unchanged", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  await start(env, "old", counts(oldRows));
  await seedAll(env, "old", oldRows);
  assert.equal((await commit(env, "old")).status, 200);
  const before = await liveIds(db);

  await start(env, "new", counts(newRows));
  await seed(env, "new", "channels", newRows.channels);
  const result = await commit(env, "new");
  assert.equal(result.status, 409);
  assert.deepEqual(await liveIds(db), before);
});

test("a failed live swap rolls back every table", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const invalidRows = dataset("2", { invalidEntrySongId: 99999 });
  await start(env, "old", counts(oldRows));
  await seedAll(env, "old", oldRows);
  assert.equal((await commit(env, "old")).status, 200);
  const before = await liveIds(db);

  await start(env, "new", counts(invalidRows));
  await seedAll(env, "new", invalidRows);
  const result = await commit(env, "new");
  assert.equal(result.status, 500);
  assert.deepEqual(await liveIds(db), before);
});

test("successful commit deletes stale live rows and repeated commit is idempotent", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const oldRows = dataset("1");
  const newRows = dataset("2");
  await start(env, "old", counts(oldRows));
  await seedAll(env, "old", oldRows);
  assert.equal((await commit(env, "old")).status, 200);
  await start(env, "new", counts(newRows));
  await seedAll(env, "new", newRows);
  assert.equal((await commit(env, "new")).status, 200);
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-2"],
    videos: ["video-2"],
    song_groups: ["group-2"],
    songs: [2],
    song_entries: [2],
  });
  assert.deepEqual(await commit(env, "new"), { status: 200, body: { ok: true, version: "new", status: "ready" } });
  const newer = dataset("3");
  await start(env, "newer", counts(newer));
  const oldRetry = await commit(env, "new");
  assert.equal(oldRetry.status, 409);
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-2"],
    videos: ["video-2"],
    song_groups: ["group-2"],
    songs: [2],
    song_entries: [2],
  });
});

test("snapshot import commits against the current Drizzle migration schema", async (t) => {
  const db = await createMigratedDb();
  t.after(() => db.close());
  const env = { DB: db, SEED_TOKEN: "test-token" };
  const rows = dataset("7");

  assert.equal((await start(env, "drizzle-v1", counts(rows))).status, 200);
  await seedAll(env, "drizzle-v1", rows);
  assert.equal((await commit(env, "drizzle-v1")).status, 200);
  assert.deepEqual(await liveIds(db), {
    channels: ["channel-7"],
    videos: ["video-7"],
    song_groups: ["group-7"],
    songs: [7],
    song_entries: [7],
  });
  assert.deepEqual(await queryRows(db, "SELECT version, status, expected_json FROM dataset_meta WHERE id = 1"), [
    {
      version: "drizzle-v1",
      status: "ready",
      expected_json: JSON.stringify(counts(rows)),
    },
  ]);
});
