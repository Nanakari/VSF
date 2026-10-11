import { json, requestText } from "./http.js";

// The suffix keeps the versioned staging schema separate from the original
// shared staging tables.  Every row also carries its snapshot version so two
// imports can safely coexist while one of them is being superseded.
const SNAPSHOT_STAGING_TABLES = Object.freeze({
  channels: "snapshot_channels_v2",
  videos: "snapshot_videos_v2",
  song_groups: "snapshot_song_groups_v2",
  songs: "snapshot_songs_v2",
  song_entries: "snapshot_song_entries_v2",
});
const SEED_TABLES = new Set(Object.keys(SNAPSHOT_STAGING_TABLES));
const PATCH_MAX_OPERATIONS = 80;
const PATCH_TABLES = new Set(SEED_TABLES);
const PATCH_LIVE_TABLES = Object.freeze({
  channels: "channels",
  videos: "videos",
  song_groups: "song_groups",
  songs: "songs",
  song_entries: "song_entries",
});
const PATCH_KEY_COLUMNS = Object.freeze({
  channels: "channel_id",
  videos: "video_id",
  song_groups: "group_key",
  songs: "id",
  song_entries: "id",
});

function snapshotExpectedTables(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("snapshot tables must be an object");
  }
  const expected = {};
  for (const table of SEED_TABLES) {
    const count = value[table];
    if (!Number.isSafeInteger(count) || count < 0) {
      throw new Error(`invalid row count for ${table}`);
    }
    expected[table] = count;
  }
  return expected;
}

function requireSeedToken(request, env) {
  const configured = String(env.SEED_TOKEN || "");
  const supplied = request.headers.get("x-seed-token") || "";
  return Boolean(configured) && supplied === configured;
}

function required(row, key) {
  return row[key] !== undefined && row[key] !== null;
}

function seedStatements(table, rows, env, version, targetTable = SNAPSHOT_STAGING_TABLES[table]) {
  const statements = [];
  for (const row of rows) {
    if (table === "channels" && required(row, "channel_id") && required(row, "channel_title")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, channel_id, channel_title)
        SELECT ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, channel_id) DO UPDATE SET
          channel_title = excluded.channel_title
      `).bind(version, row.channel_id, row.channel_title, version));
    } else if (table === "videos" && required(row, "video_id") && required(row, "channel_id") && required(row, "title") && required(row, "url") && required(row, "indexed_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, video_id, channel_id, title, published_at, url, indexed_at)
        SELECT ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, video_id) DO UPDATE SET
          channel_id = excluded.channel_id,
          title = excluded.title,
          published_at = excluded.published_at,
          url = excluded.url,
          indexed_at = excluded.indexed_at
      `).bind(version, row.video_id, row.channel_id, row.title, row.published_at ?? null, row.url, row.indexed_at, version));
    } else if (table === "song_groups" && required(row, "group_key") && required(row, "song_title") && required(row, "title_search") && required(row, "artist_search") && required(row, "entry_count") && required(row, "channel_count")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, group_key) DO UPDATE SET
          song_title = excluded.song_title,
          artist = excluded.artist,
          title_search = excluded.title_search,
          artist_search = excluded.artist_search,
          entry_count = excluded.entry_count,
          channel_count = excluded.channel_count
      `).bind(version, row.group_key, row.song_title, row.artist ?? "", row.title_search, row.artist_search, row.entry_count, row.channel_count, version));
    } else if (table === "songs" && required(row, "id") && required(row, "channel_id") && required(row, "canonical_song_title") && required(row, "normalized_song_title") && required(row, "group_key") && required(row, "created_at") && required(row, "updated_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, id) DO UPDATE SET
          channel_id = excluded.channel_id,
          canonical_song_title = excluded.canonical_song_title,
          normalized_song_title = excluded.normalized_song_title,
          artist = excluded.artist,
          group_key = excluded.group_key,
          created_at = excluded.created_at,
          updated_at = excluded.updated_at
      `).bind(version, row.id, row.channel_id, row.canonical_song_title, row.normalized_song_title, row.artist ?? "", row.group_key, row.created_at, row.updated_at, version));
    } else if (table === "song_entries" && required(row, "id") && required(row, "song_id") && required(row, "group_key") && required(row, "video_id") && required(row, "timestamp_text") && required(row, "seconds") && required(row, "raw_song_title") && required(row, "normalized_song_title") && required(row, "source_comment") && required(row, "jump_url") && required(row, "created_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (snapshot_version, id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1 FROM dataset_meta
          WHERE id = 1 AND version = ? AND status = 'loading'
        )
        ON CONFLICT(snapshot_version, id) DO UPDATE SET
          song_id = excluded.song_id,
          group_key = excluded.group_key,
          video_id = excluded.video_id,
          timestamp_text = excluded.timestamp_text,
          seconds = excluded.seconds,
          raw_song_title = excluded.raw_song_title,
          normalized_song_title = excluded.normalized_song_title,
          source_comment = excluded.source_comment,
          jump_url = excluded.jump_url,
          created_at = excluded.created_at
      `).bind(version, row.id, row.song_id, row.group_key, row.video_id, row.timestamp_text, row.seconds, row.raw_song_title, row.normalized_song_title, row.source_comment, row.jump_url, row.created_at, version));
    } else {
      throw new Error(`invalid ${table} row`);
    }
  }
  return statements;
}

function snapshotSchemaStatements(env) {
  return [
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS dataset_meta (
        id INTEGER PRIMARY KEY DEFAULT 1,
        version TEXT NOT NULL,
        status TEXT NOT NULL,
        expected_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_channels_v2 (
        snapshot_version TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        channel_title TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, channel_id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_videos_v2 (
        snapshot_version TEXT NOT NULL,
        video_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at TEXT,
        url TEXT NOT NULL,
        indexed_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, video_id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_song_groups_v2 (
        snapshot_version TEXT NOT NULL,
        group_key TEXT NOT NULL,
        song_title TEXT NOT NULL,
        artist TEXT NOT NULL,
        title_search TEXT NOT NULL,
        artist_search TEXT NOT NULL,
        entry_count INTEGER NOT NULL,
        channel_count INTEGER NOT NULL,
        PRIMARY KEY (snapshot_version, group_key)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_songs_v2 (
        snapshot_version TEXT NOT NULL,
        id INTEGER NOT NULL,
        channel_id TEXT NOT NULL,
        canonical_song_title TEXT NOT NULL,
        normalized_song_title TEXT NOT NULL,
        artist TEXT NOT NULL,
        group_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_song_entries_v2 (
        snapshot_version TEXT NOT NULL,
        id INTEGER NOT NULL,
        song_id INTEGER NOT NULL,
        group_key TEXT NOT NULL,
        video_id TEXT NOT NULL,
        timestamp_text TEXT NOT NULL,
        seconds INTEGER NOT NULL,
        raw_song_title TEXT NOT NULL,
        normalized_song_title TEXT NOT NULL,
        source_comment TEXT NOT NULL,
        jump_url TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (snapshot_version, id)
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS dataset_patch_meta (
        id INTEGER PRIMARY KEY DEFAULT 1,
        version TEXT NOT NULL,
        base_version TEXT NOT NULL,
        status TEXT NOT NULL,
        expected_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS dataset_patch_rows (
        patch_version TEXT NOT NULL,
        table_name TEXT NOT NULL,
        row_key TEXT NOT NULL,
        operation TEXT NOT NULL,
        payload_json TEXT,
        PRIMARY KEY (patch_version, table_name, row_key)
      )
    `),
  ];
}

function patchMeta(env) {
  try {
    return env.DB.prepare(
      "SELECT version, base_version, status, expected_json FROM dataset_patch_meta WHERE id = 1",
    ).first();
  } catch {
    return null;
  }
}

function patchExpectedChanges(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("patch changes must be an object");
  }
  const changes = {};
  let total = 0;
  for (const table of PATCH_TABLES) {
    const entry = value[table];
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`invalid patch change counts for ${table}`);
    }
    const upserts = entry.upserts;
    const deletes = entry.deletes;
    if (!Number.isSafeInteger(upserts) || upserts < 0
      || !Number.isSafeInteger(deletes) || deletes < 0) {
      throw new Error(`invalid patch change counts for ${table}`);
    }
    changes[table] = { upserts, deletes };
    total += upserts + deletes;
  }
  if (total < 1 || total > PATCH_MAX_OPERATIONS) {
    throw new Error("patch change count is outside the supported range");
  }
  return changes;
}

function patchExpectedFromState(state) {
  try {
    const payload = JSON.parse(state?.expected_json || "{}");
    return {
      tables: snapshotExpectedTables(payload.tables),
      changes: patchExpectedChanges(payload.changes),
    };
  } catch {
    return null;
  }
}

function patchCountCondition(version, changes) {
  const conditions = [];
  const params = [];
  for (const table of PATCH_TABLES) {
    for (const [operation, count] of [["upsert", changes[table].upserts], ["delete", changes[table].deletes]]) {
      conditions.push(`(
        SELECT COUNT(*) FROM dataset_patch_rows
        WHERE patch_version = ? AND table_name = ? AND operation = ?
      ) = ?`);
      params.push(version, table, operation, count);
    }
  }
  return { sql: conditions.join(" AND "), params };
}

function patchActiveGuard(version, baseVersion) {
  return `EXISTS (
    SELECT 1
    FROM dataset_patch_meta AS patch
    JOIN dataset_meta AS snapshot ON snapshot.id = 1
    WHERE patch.id = 1
      AND patch.version = ?
      AND patch.base_version = ?
      AND patch.status = 'committing'
      AND snapshot.version = ?
      AND snapshot.status = 'ready'
  )`;
}

function patchActiveParams(version, baseVersion) {
  return [version, baseVersion, baseVersion];
}

function patchRowKey(table, row) {
  if (!row || typeof row !== "object" || Array.isArray(row)) {
    throw new Error(`invalid ${table} patch row`);
  }
  const key = PATCH_KEY_COLUMNS[table];
  if (!required(row, key)) throw new Error(`missing ${table} patch key`);
  const value = String(row[key]).trim();
  if (!value) throw new Error(`empty ${table} patch key`);
  return value;
}

function validatePatchUpsert(table, row) {
  if (table === "channels" && required(row, "channel_id") && required(row, "channel_title")) return;
  if (table === "videos" && required(row, "video_id") && required(row, "channel_id") && required(row, "title") && required(row, "url") && required(row, "indexed_at")) return;
  if (table === "song_groups" && required(row, "group_key") && required(row, "song_title") && required(row, "title_search") && required(row, "artist_search") && required(row, "entry_count") && required(row, "channel_count")) return;
  if (table === "songs" && required(row, "id") && required(row, "channel_id") && required(row, "canonical_song_title") && required(row, "normalized_song_title") && required(row, "group_key") && required(row, "created_at") && required(row, "updated_at")) return;
  if (table === "song_entries" && required(row, "id") && required(row, "song_id") && required(row, "group_key") && required(row, "video_id") && required(row, "timestamp_text") && required(row, "seconds") && required(row, "raw_song_title") && required(row, "normalized_song_title") && required(row, "source_comment") && required(row, "jump_url") && required(row, "created_at")) return;
  throw new Error(`invalid ${table} patch row`);
}

function patchWriteStatements(table, upserts, deletes, env, version) {
  const statements = [];
  const deleteKeys = new Set(deletes.map((value) => String(value).trim()));
  const upsertKeys = new Set();
  for (const row of upserts) {
    validatePatchUpsert(table, row);
    const key = patchRowKey(table, row);
    if (upsertKeys.has(key) || deleteKeys.has(key)) {
      throw new Error(`duplicate ${table} patch key`);
    }
    upsertKeys.add(key);
    statements.push(env.DB.prepare(`
      INSERT INTO dataset_patch_rows (patch_version, table_name, row_key, operation, payload_json)
      SELECT ?, ?, ?, 'upsert', ?
      WHERE EXISTS (
        SELECT 1 FROM dataset_patch_meta
        WHERE id = 1 AND version = ? AND status = 'loading'
      )
      ON CONFLICT(patch_version, table_name, row_key) DO UPDATE SET
        operation = excluded.operation,
        payload_json = excluded.payload_json
    `).bind(version, table, key, JSON.stringify(row), version));
  }
  for (const value of deletes) {
    const key = String(value).trim();
    if (!key || upsertKeys.has(key) || deleteKeys.size !== deletes.length) {
      throw new Error(`invalid ${table} patch delete key`);
    }
    statements.push(env.DB.prepare(`
      INSERT INTO dataset_patch_rows (patch_version, table_name, row_key, operation, payload_json)
      SELECT ?, ?, ?, 'delete', NULL
      WHERE EXISTS (
        SELECT 1 FROM dataset_patch_meta
        WHERE id = 1 AND version = ? AND status = 'loading'
      )
      ON CONFLICT(patch_version, table_name, row_key) DO UPDATE SET
        operation = excluded.operation,
        payload_json = excluded.payload_json
    `).bind(version, table, key, version));
  }
  return statements;
}

function patchDeleteStatement(table, key, env, version, baseVersion) {
  const keyColumn = PATCH_KEY_COLUMNS[table];
  const keyValue = (table === "songs" || table === "song_entries") ? Number(key) : key;
  return env.DB.prepare(`
    DELETE FROM ${PATCH_LIVE_TABLES[table]}
    WHERE ${keyColumn} = ? AND ${patchActiveGuard(version, baseVersion)}
  `).bind(keyValue, ...patchActiveParams(version, baseVersion));
}

function patchUpsertStatement(table, row, env, version, baseVersion) {
  const activeGuard = patchActiveGuard(version, baseVersion);
  const activeParams = patchActiveParams(version, baseVersion);
  if (table === "channels") {
    return env.DB.prepare(`
      INSERT INTO channels (channel_id, channel_title)
      SELECT ?, ? WHERE ${activeGuard}
      ON CONFLICT(channel_id) DO UPDATE SET channel_title = excluded.channel_title
    `).bind(row.channel_id, row.channel_title, ...activeParams);
  }
  if (table === "videos") {
    return env.DB.prepare(`
      INSERT INTO videos (video_id, channel_id, title, published_at, url, indexed_at)
      SELECT ?, ?, ?, ?, ?, ? WHERE ${activeGuard}
      ON CONFLICT(video_id) DO UPDATE SET
        channel_id = excluded.channel_id,
        title = excluded.title,
        published_at = excluded.published_at,
        url = excluded.url,
        indexed_at = excluded.indexed_at
    `).bind(row.video_id, row.channel_id, row.title, row.published_at ?? null, row.url, row.indexed_at, ...activeParams);
  }
  if (table === "song_groups") {
    return env.DB.prepare(`
      INSERT INTO song_groups (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
      SELECT ?, ?, ?, ?, ?, ?, ? WHERE ${activeGuard}
      ON CONFLICT(group_key) DO UPDATE SET
        song_title = excluded.song_title,
        artist = excluded.artist,
        title_search = excluded.title_search,
        artist_search = excluded.artist_search,
        entry_count = excluded.entry_count,
        channel_count = excluded.channel_count
    `).bind(row.group_key, row.song_title, row.artist ?? "", row.title_search, row.artist_search, row.entry_count, row.channel_count, ...activeParams);
  }
  if (table === "songs") {
    return env.DB.prepare(`
      INSERT INTO songs (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
      SELECT ?, ?, ?, ?, ?, ?, ?, ? WHERE ${activeGuard}
      ON CONFLICT(id) DO UPDATE SET
        channel_id = excluded.channel_id,
        canonical_song_title = excluded.canonical_song_title,
        normalized_song_title = excluded.normalized_song_title,
        artist = excluded.artist,
        group_key = excluded.group_key,
        created_at = excluded.created_at,
        updated_at = excluded.updated_at
    `).bind(row.id, row.channel_id, row.canonical_song_title, row.normalized_song_title, row.artist ?? "", row.group_key, row.created_at, row.updated_at, ...activeParams);
  }
  return env.DB.prepare(`
    INSERT INTO song_entries (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
    SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE ${activeGuard}
    ON CONFLICT(id) DO UPDATE SET
      song_id = excluded.song_id,
      group_key = excluded.group_key,
      video_id = excluded.video_id,
      timestamp_text = excluded.timestamp_text,
      seconds = excluded.seconds,
      raw_song_title = excluded.raw_song_title,
      normalized_song_title = excluded.normalized_song_title,
      source_comment = excluded.source_comment,
      jump_url = excluded.jump_url,
      created_at = excluded.created_at
  `).bind(row.id, row.song_id, row.group_key, row.video_id, row.timestamp_text, row.seconds, row.raw_song_title, row.normalized_song_title, row.source_comment, row.jump_url, row.created_at, ...activeParams);
}

async function snapshotMeta(env) {
  try {
    return await env.DB.prepare(
      "SELECT version, status, expected_json FROM dataset_meta WHERE id = 1",
    ).first();
  } catch {
    return null;
  }
}

async function snapshotState(env, version) {
  const row = await snapshotMeta(env);
  if (!row || row.version !== version || row.status !== "loading") return null;
  return row;
}

function expectedTablesEqual(left, right) {
  return [...SEED_TABLES].every((table) => left?.[table] === right?.[table]);
}

function expectedTablesFromState(state) {
  try {
    return snapshotExpectedTables(JSON.parse(state?.expected_json || "{}"));
  } catch {
    return null;
  }
}

function snapshotCountCondition(expected) {
  const countChecks = [...SEED_TABLES].map((table) =>
    `(SELECT COUNT(*) FROM ${SNAPSHOT_STAGING_TABLES[table]} WHERE snapshot_version = ?) = ?`,
  );
  return countChecks.join(" AND ");
}

function snapshotCountParams(version, expected) {
  return [...SEED_TABLES].flatMap((table) => [version, expected[table]]);
}

export async function startPatch(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  const baseVersion = requestText(payload?.base_version, 120);
  if (!version || !baseVersion) return json({ ok: false, message: "Patch versions are required" }, 400);

  let nextTables;
  let changes;
  try {
    nextTables = snapshotExpectedTables(payload?.tables);
    changes = patchExpectedChanges(payload?.changes);
  } catch {
    return json({ ok: false, message: "Missing or invalid patch counts" }, 400);
  }

  try {
    await env.DB.batch(snapshotSchemaStatements(env));
    const current = await snapshotMeta(env);
    if (current?.version === version && current.status === "ready") {
      return json({ ok: true, version, status: "ready" });
    }
    if (!current || current.status !== "ready" || current.version !== baseVersion) {
      return json({ ok: false, message: "Incremental patch base version is stale" }, 409);
    }

    const expectedJson = JSON.stringify({ tables: nextTables, changes });
    const existing = await patchMeta(env);
    if (existing?.version === version && ["loading", "ready"].includes(existing.status)) {
      const existingExpected = patchExpectedFromState(existing);
      if (existing.base_version !== baseVersion
        || JSON.stringify(existingExpected) !== JSON.stringify({ tables: nextTables, changes })) {
        return json({ ok: false, message: "Patch version already exists with different metadata" }, 409);
      }
      return json({ ok: true, version, status: existing.status });
    }

    await env.DB.batch([
      env.DB.prepare("DELETE FROM dataset_patch_rows WHERE patch_version <> ?").bind(version),
      env.DB.prepare(`
        INSERT INTO dataset_patch_meta (id, version, base_version, status, expected_json, updated_at)
        VALUES (1, ?, ?, 'loading', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
          version = excluded.version,
          base_version = excluded.base_version,
          status = excluded.status,
          expected_json = excluded.expected_json,
          updated_at = excluded.updated_at
      `).bind(version, baseVersion, expectedJson),
    ]);
    const finalState = await patchMeta(env);
    if (!finalState || finalState.version !== version || finalState.base_version !== baseVersion) {
      return json({ ok: false, message: "Patch was superseded before it became active" }, 409);
    }
    return json({ ok: true, version, status: finalState.status });
  } catch (error) {
    console.error("patch start failed", error);
    return json({ ok: false, message: "Patch start failed" }, 500);
  }
}

export async function patch(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  const table = String(payload?.table || "");
  const upserts = payload?.upserts;
  const deletes = payload?.deletes;
  if (!version || !PATCH_TABLES.has(table) || !Array.isArray(upserts) || !Array.isArray(deletes)
    || upserts.length + deletes.length < 1
    || upserts.length + deletes.length > PATCH_MAX_OPERATIONS) {
    return json({ ok: false, message: "Invalid patch batch" }, 400);
  }
  const current = await patchMeta(env);
  if (!current || current.version !== version || current.status !== "loading") {
    return json({ ok: false, message: "Patch is not active" }, 409);
  }
  try {
    const statements = [
      env.DB.prepare(`
        UPDATE dataset_patch_meta
        SET status = 'loading'
        WHERE id = 1 AND version = ? AND status = 'loading'
      `).bind(version),
      ...patchWriteStatements(table, upserts, deletes, env, version),
    ];
    const results = await env.DB.batch(statements);
    if (Number(results?.[0]?.meta?.changes) !== 1) {
      return json({ ok: false, message: "Patch is no longer active" }, 409);
    }
    return json({ ok: true, version, table, inserted: upserts.length, deleted: deletes.length });
  } catch (error) {
    console.error("patch batch failed", table, error);
    return json({ ok: false, message: "Patch batch failed" }, 400);
  }
}

export async function commitPatch(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  if (!version) return json({ ok: false, message: "Missing patch version" }, 400);
  const current = await patchMeta(env);
  if (!current || current.version !== version) {
    return json({ ok: false, message: "Patch is not ready for commit" }, 409);
  }
  if (current.status === "ready") {
    const snapshot = await snapshotMeta(env);
    if (snapshot?.version === version && snapshot.status === "ready") {
      return json({ ok: true, version, status: "ready" });
    }
    return json({ ok: false, message: "Patch was superseded before commit" }, 409);
  }
  if (current.status !== "loading") {
    return json({ ok: false, message: "Patch is not ready for commit" }, 409);
  }
  const expected = patchExpectedFromState(current);
  if (!expected) return json({ ok: false, message: "Patch metadata is invalid" }, 409);

  try {
    const patchRows = (await env.DB.prepare(`
      SELECT table_name, row_key, operation, payload_json
      FROM dataset_patch_rows
      WHERE patch_version = ?
      ORDER BY table_name, row_key
    `).bind(version).all()).results || [];
    const deleteRows = [];
    const upsertRows = [];
    for (const row of patchRows) {
      if (!PATCH_TABLES.has(row.table_name) || !["upsert", "delete"].includes(row.operation)) {
        return json({ ok: false, message: "Patch contains an invalid operation" }, 400);
      }
      if (row.operation === "delete") {
        if (!String(row.row_key || "").trim()) return json({ ok: false, message: "Patch contains an empty delete key" }, 400);
        deleteRows.push(row);
        continue;
      }
      let patchRow;
      try {
        patchRow = JSON.parse(row.payload_json || "");
        validatePatchUpsert(row.table_name, patchRow);
        if (patchRowKey(row.table_name, patchRow) !== String(row.row_key)) {
          throw new Error("patch key mismatch");
        }
      } catch {
        return json({ ok: false, message: "Patch contains an invalid row" }, 400);
      }
      upsertRows.push({ table: row.table_name, key: row.row_key, row: patchRow });
    }

    const countGuard = patchCountCondition(version, expected.changes);
    const statements = [
      // A retained song/entry may move away from a group deleted below. Check
      // references after all row changes in this atomic batch, not midway
      // through it. COMMIT still rejects dangling references and rolls back.
      // https://developers.cloudflare.com/d1/sql-api/foreign-keys/
      env.DB.prepare("PRAGMA defer_foreign_keys = ON"),
      env.DB.prepare(`
        UPDATE dataset_patch_meta
        SET status = 'committing', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND base_version = ? AND status = 'loading'
          AND EXISTS (
            SELECT 1 FROM dataset_meta
            WHERE id = 1 AND version = ? AND status = 'ready'
          )
          AND ${countGuard.sql}
      `).bind(version, current.base_version, current.base_version, ...countGuard.params),
    ];

    for (const table of ["song_entries", "songs", "song_groups", "videos", "channels"]) {
      for (const row of deleteRows.filter((candidate) => candidate.table_name === table)) {
        statements.push(patchDeleteStatement(table, row.row_key, env, version, current.base_version));
      }
    }
    for (const table of ["channels", "videos", "song_groups", "songs", "song_entries"]) {
      for (const item of upsertRows.filter((candidate) => candidate.table === table)) {
        statements.push(patchUpsertStatement(table, item.row, env, version, current.base_version));
      }
    }
    statements.push(
      env.DB.prepare(`
        UPDATE dataset_meta
        SET version = ?, status = 'ready', expected_json = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND status = 'ready'
          AND EXISTS (
            SELECT 1 FROM dataset_patch_meta
            WHERE id = 1 AND version = ? AND base_version = ? AND status = 'committing'
          )
      `).bind(version, JSON.stringify(expected.tables), current.base_version, version, current.base_version),
      env.DB.prepare(`
        UPDATE dataset_patch_meta
        SET status = 'ready', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND status = 'committing'
          AND EXISTS (
            SELECT 1 FROM dataset_meta
            WHERE id = 1 AND version = ? AND status = 'ready'
          )
      `).bind(version, version),
      env.DB.prepare("DELETE FROM dataset_patch_rows WHERE patch_version = ?").bind(version),
    );
    await env.DB.batch(statements);

    const finalSnapshot = await snapshotMeta(env);
    const finalPatch = await patchMeta(env);
    if (finalSnapshot?.version === version && finalSnapshot.status === "ready"
      && finalPatch?.version === version && finalPatch.status === "ready") {
      return json({ ok: true, version, status: "ready" });
    }
    return json({ ok: false, message: "Patch was incomplete; live data was kept" }, 409);
  } catch (error) {
    console.error("patch commit failed", error);
    return json({ ok: false, message: "Patch commit failed; previous data was kept" }, 500);
  }
}

export async function startSnapshot(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  if (!version) return json({ ok: false, message: "Missing snapshot version" }, 400);
  let expectedTables;
  try {
    expectedTables = snapshotExpectedTables(payload?.tables);
  } catch {
    return json({ ok: false, message: "Missing or invalid snapshot table counts" }, 400);
  }

  try {
    // DDL is kept in its own batch so retries work even when dataset_meta does
    // not exist yet.  The metadata update and version-scoped cleanup below are
    // still one transaction.
    await env.DB.batch(snapshotSchemaStatements(env));
    const current = await snapshotMeta(env);
    const expectedJson = JSON.stringify(expectedTables);
    if (current?.version === version && ["loading", "ready"].includes(current.status)) {
      const currentExpected = expectedTablesFromState(current);
      if (!expectedTablesEqual(currentExpected, expectedTables)) {
        return json({ ok: false, message: "Snapshot version already exists with different row counts" }, 409);
      }
      return json({ ok: true, version, status: current.status });
    }

    await env.DB.batch([
      ...[...SEED_TABLES].map((table) =>
        env.DB.prepare(`
          DELETE FROM ${SNAPSHOT_STAGING_TABLES[table]}
          WHERE snapshot_version <> ?
        `).bind(version),
      ),
      env.DB.prepare(`
        UPDATE dataset_patch_meta
        SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND status <> 'superseded'
      `),
      env.DB.prepare(`
        INSERT INTO dataset_meta (id, version, status, expected_json, updated_at)
        VALUES (1, ?, 'loading', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
          version = excluded.version,
          status = excluded.status,
          expected_json = excluded.expected_json,
          updated_at = excluded.updated_at
        WHERE dataset_meta.version <> excluded.version
           OR dataset_meta.status NOT IN ('loading', 'ready')
      `).bind(version, expectedJson),
    ]);

    const finalState = await snapshotMeta(env);
    if (!finalState || finalState.version !== version) {
      return json({ ok: false, message: "Snapshot was superseded before it became active" }, 409);
    }
    const finalExpected = expectedTablesFromState(finalState);
    if (!expectedTablesEqual(finalExpected, expectedTables)) {
      return json({ ok: false, message: "Snapshot version already exists with different row counts" }, 409);
    }
    return json({ ok: true, version, status: finalState.status });
  } catch (error) {
    console.error("snapshot start failed", error);
    return json({ ok: false, message: "Snapshot start failed" }, 500);
  }
}

export async function commitSnapshot(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  if (!version) return json({ ok: false, message: "Missing snapshot version" }, 400);
  const current = await snapshotMeta(env);
  if (!current || current.version !== version) {
    return json({ ok: false, message: "Snapshot is not ready for commit" }, 409);
  }
  if (current.status === "ready") {
    return json({ ok: true, version, status: "ready" });
  }
  if (current.status !== "loading") {
    return json({ ok: false, message: "Snapshot is not ready for commit" }, 409);
  }
  const expected = expectedTablesFromState(current);
  if (!expected) {
    return json({ ok: false, message: "Snapshot is incomplete; live data was kept" }, 409);
  }
  const countGuard = snapshotCountCondition(expected);
  const countParams = snapshotCountParams(version, expected);
  const activeGuard = "EXISTS (SELECT 1 FROM dataset_meta WHERE id = 1 AND version = ? AND status = 'committing')";
  const activeParams = [version];

  try {
    const statements = [
      // Count validation and the loading -> committing transition happen in
      // the same transaction as the swap.  A mismatch leaves this row in
      // loading, so all following statements become no-ops.
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'committing', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND status = 'loading'
          AND ${countGuard}
      `).bind(version, ...countParams),
      env.DB.prepare(`DELETE FROM song_entries WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM songs WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM song_groups WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM videos WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`DELETE FROM channels WHERE ${activeGuard}`).bind(...activeParams),
      env.DB.prepare(`
        INSERT INTO channels (channel_id, channel_title)
        SELECT channel_id, channel_title
        FROM ${SNAPSHOT_STAGING_TABLES.channels}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO videos (video_id, channel_id, title, published_at, url, indexed_at)
        SELECT video_id, channel_id, title, published_at, url, indexed_at
        FROM ${SNAPSHOT_STAGING_TABLES.videos}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO song_groups (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
        SELECT group_key, song_title, artist, title_search, artist_search, entry_count, channel_count
        FROM ${SNAPSHOT_STAGING_TABLES.song_groups}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO songs (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
        SELECT id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at
        FROM ${SNAPSHOT_STAGING_TABLES.songs}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        INSERT INTO song_entries (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
        SELECT id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at
        FROM ${SNAPSHOT_STAGING_TABLES.song_entries}
        WHERE snapshot_version = ? AND ${activeGuard}
      `).bind(version, ...activeParams),
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'ready', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ? AND status = 'committing'
          AND ${activeGuard}
      `).bind(version, ...activeParams),
    ];
    await env.DB.batch(statements);

    const finalState = await snapshotMeta(env);
    if (finalState?.version === version && finalState.status === "ready") {
      return json({ ok: true, version, status: "ready" });
    }
    if (finalState?.version === version && finalState.status === "loading") {
      return json({ ok: false, message: "Snapshot is incomplete; live data was kept" }, 409);
    }
    return json({ ok: false, message: "Snapshot was superseded before commit" }, 409);
  } catch (error) {
    console.error("snapshot commit failed", error);
    return json({ ok: false, message: "Snapshot commit failed; previous data was kept" }, 500);
  }
}

export async function seed(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const table = String(payload?.table || "");
  const rows = payload?.rows;
  const version = requestText(payload?.version || request.headers.get("x-seed-version"), 120);
  if (!SEED_TABLES.has(table) || !Array.isArray(rows) || rows.length === 0 || rows.length > 90) {
    return json({ ok: false, message: "Invalid seed batch" }, 400);
  }
  if (!version) {
    return json({ ok: false, message: "Snapshot version is required; start a snapshot before seeding" }, 409);
  }
  if (!(await snapshotState(env, version))) {
    return json({ ok: false, message: "Snapshot is not active" }, 409);
  }
  try {
    // The guard is the first statement in the same D1 transaction as every
    // row write.  A request that was checked before a newer start cannot
    // insert into the newer snapshot's staging rows.
    const statements = [
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'loading'
        WHERE id = 1 AND version = ? AND status = 'loading'
      `).bind(version),
      ...seedStatements(table, rows, env, version),
    ];
    const results = await env.DB.batch(statements);
    const guardChanges = Number(results?.[0]?.meta?.changes);
    if (guardChanges !== 1) {
      return json({ ok: false, message: "Snapshot is no longer active" }, 409);
    }
    return json({ ok: true, table, inserted: rows.length, version });
  } catch (error) {
    console.error("seed failed", table, error);
    return json({ ok: false, message: "Seed batch failed" }, 500);
  }
}
