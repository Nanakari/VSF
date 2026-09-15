import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import worker from "../worker/index.js";
import { SqliteD1 } from "./helpers/sqlite_d1.mjs";

const fixturePath = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "search_contract.json");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

function titleSearch(group) {
  return JSON.stringify({
    normalized: group.normalized_titles,
    compact: group.compact_titles,
  });
}

async function createDb() {
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
    for (const statement of statements) await db.prepare(statement).run();
  }

  await db.batch(fixture.channels.map((row) => db.prepare(
    "INSERT INTO channels (channel_id, channel_title) VALUES (?, ?)",
  ).bind(row.channel_id, row.channel_title)));
  await db.batch(fixture.videos.map((row) => db.prepare(
    "INSERT INTO videos (video_id, channel_id, title, published_at, url, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
  ).bind(row.video_id, row.channel_id, row.title, row.published_at, row.url, row.indexed_at)));
  await db.batch(fixture.groups.map((row) => db.prepare(
    "INSERT INTO song_groups (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
  ).bind(row.group_key, row.song_title, row.artist, titleSearch(row), row.artist_search, row.entry_count, row.channel_count)));

  const entryBySong = new Map(fixture.entries.map((row) => [row.song_id, row]));
  await db.batch(fixture.songs.map((row) => {
    const entry = entryBySong.get(row.id);
    return db.prepare(
      "INSERT INTO songs (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(
      row.id,
      fixture.videos.find((video) => video.video_id === entry.video_id).channel_id,
      entry.raw_song_title,
      entry.raw_song_title.toLocaleLowerCase(),
      row.artist,
      row.group_key,
      "2026-01-01T00:00:00Z",
      "2026-01-01T00:00:00Z",
    );
  }));
  const groupBySong = new Map(fixture.songs.map((row) => [row.id, row.group_key]));
  await db.batch(fixture.entries.map((row) => db.prepare(
    "INSERT INTO song_entries (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
  ).bind(
    row.id,
    row.song_id,
    groupBySong.get(row.song_id),
    row.video_id,
    row.timestamp_text,
    row.seconds,
    row.raw_song_title,
    row.raw_song_title.toLocaleLowerCase(),
    row.source_comment,
    `https://example.test/${row.video_id}#t=${row.seconds}`,
    "2026-01-01T00:00:00Z",
  )));
  return db;
}

async function getJson(env, query) {
  const response = await worker.fetch(new Request(`https://search.test/api/search?${new URLSearchParams(query)}`), env);
  assert.equal(response.status, 200);
  return response.json();
}

function groupIds(payload) {
  return payload.groups.map((group) => group.id);
}

test("Worker search follows the shared grouped contract without songs.artist_search", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db };

  for (const query of fixture.queries) {
    const payload = await getJson(env, query);
    assert.deepEqual(groupIds(payload), query.expected_groups, query.name);
    assert.equal(payload.total, query.expected_groups.length, query.name);
    if (query.expected_entry_count !== undefined) {
      assert.equal(payload.groups.length, 1, query.name);
      assert.equal(payload.groups[0].entryCount, query.expected_entry_count, query.name);
    }
  }
});

test("Worker group pagination, entry pagination, and artist scoping are stable", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db };

  const pageOne = await getJson(env, { page: "1", pageSize: "3" });
  const pageTwo = await getJson(env, { page: "2", pageSize: "3" });
  assert.equal(pageOne.total, 10);
  assert.deepEqual(groupIds(pageOne), [
    "stellarstellar::ado",
    "abcdefghij::ado",
    "encore::ado",
  ]);
  assert.deepEqual(groupIds(pageTwo), [
    "starlight::ado",
    "alphasong::ado",
    "betasong::ado",
  ]);

  const unknownAuthor = await getJson(env, {
    song: "Encore",
    artist: "Ado",
    pageSize: "10",
  });
  assert.equal(unknownAuthor.groups[0].entryCount, 1);
  const entries = await worker.fetch(new Request(
    "https://search.test/api/entries?groupKey=encore%3A%3Aado&artist=Ado&pageSize=10",
  ), env);
  assert.equal(entries.status, 200);
  const entryPayload = await entries.json();
  assert.equal(entryPayload.total, 1);
  assert.deepEqual(entryPayload.entries.map((row) => row.timestampText), ["00:25"]);

  const stellarPage = await worker.fetch(new Request(
    "https://search.test/api/entries?groupKey=stellar%3A%3Aado&channelId=chan-a&page=2&pageSize=2",
  ), env);
  // The request above intentionally uses a missing group key to ensure the
  // endpoint remains a normal empty page rather than broadening the query.
  assert.equal(stellarPage.status, 200);
  assert.equal((await stellarPage.json()).total, 0);

  const actualStellar = await worker.fetch(new Request(
    "https://search.test/api/entries?groupKey=stellarstellar%3A%3Aado&channelId=chan-a&page=2&pageSize=2",
  ), env);
  assert.equal(actualStellar.status, 200);
  const stellarPayload = await actualStellar.json();
  assert.equal(stellarPayload.total, 3);
  assert.deepEqual(stellarPayload.entries.map((row) => row.timestampText), ["00:05"]);
});

test("Worker entries use one JSON bind for large merged song sets", async (t) => {
  const db = await createDb();
  t.after(() => db.close());
  const env = { DB: db };
  const groupKey = "bulk::ado";
  await db.prepare(
    "INSERT INTO song_groups (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
  ).bind(
    groupKey,
    "Bulk",
    "Ado",
    JSON.stringify({ normalized: ["bulk"], compact: ["bulk"] }),
    "ado",
    120,
    1,
  ).run();
  const songs = [];
  const entries = [];
  for (let index = 0; index < 120; index += 1) {
    const id = 1000 + index;
    const title = `Bulk ${index} / Ado`;
    songs.push(db.prepare(
      "INSERT INTO songs (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(id, "chan-c", title, title.toLocaleLowerCase(), "Ado", groupKey, "2026-01-01", "2026-01-01"));
    entries.push(db.prepare(
      "INSERT INTO song_entries (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(id, id, groupKey, "c-one", `10:${String(index).padStart(2, "0")}`, 1000 + index, title, title.toLocaleLowerCase(), "bulk", `https://example.test/c-one#t=${1000 + index}`, "2026-01-01"));
  }
  await db.batch([...songs, ...entries]);
  const response = await worker.fetch(new Request(
    `https://search.test/api/entries?groupKey=${encodeURIComponent(groupKey)}&artist=Ado&page=120&pageSize=1`,
  ), env);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.total, 120);
  assert.deepEqual(payload.entries.map((row) => row.timestampText), ["10:119"]);
});
