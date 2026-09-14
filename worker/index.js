const pageHtml = "__SITE_HTML__";
const stylesCss = "__SITE_CSS__";
const clientJs = "__SITE_JS__";
const faviconSvg = "__SITE_FAVICON__";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

const SNAPSHOT_STAGING_TABLES = Object.freeze({
  channels: "snapshot_channels",
  videos: "snapshot_videos",
  song_groups: "snapshot_song_groups",
  songs: "snapshot_songs",
  song_entries: "snapshot_song_entries",
});
const SEED_TABLES = new Set(Object.keys(SNAPSHOT_STAGING_TABLES));

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

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: JSON_HEADERS,
  });
}

function textResponse(value, contentType, cacheControl = "no-store") {
  return new Response(value, {
    headers: {
      "content-type": contentType,
      "cache-control": cacheControl,
    },
  });
}

function requestText(value, maxLength = 120) {
  return String(value ?? "").trim().slice(0, maxLength);
}

function likeValue(value) {
  return `%${value}%`;
}

function toCount(value) {
  return Number(value || 0);
}

async function queryOverview(env) {
  const [channelsCount, videosCount, songsCount, entriesCount, channelsResult, updatedResult] = await env.DB.batch([
    env.DB.prepare("SELECT COUNT(*) AS count FROM channels"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM videos"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM songs"),
    env.DB.prepare("SELECT COUNT(*) AS count FROM song_entries"),
    env.DB.prepare(`
      SELECT
        c.channel_id,
        c.channel_title,
        COALESCE(video_counts.video_count, 0) AS video_count,
        COALESCE(song_counts.song_count, 0) AS song_count,
        COALESCE(entry_counts.entry_count, 0) AS entry_count
      FROM channels c
      LEFT JOIN (
        SELECT channel_id, COUNT(*) AS video_count
        FROM videos
        GROUP BY channel_id
      ) video_counts ON video_counts.channel_id = c.channel_id
      LEFT JOIN (
        SELECT channel_id, COUNT(*) AS song_count
        FROM songs
        GROUP BY channel_id
      ) song_counts ON song_counts.channel_id = c.channel_id
      LEFT JOIN (
        SELECT v.channel_id, COUNT(e.id) AS entry_count
        FROM song_entries e
        JOIN videos v ON v.video_id = e.video_id
        GROUP BY v.channel_id
      ) entry_counts ON entry_counts.channel_id = c.channel_id
      ORDER BY c.channel_title
    `),
    env.DB.prepare("SELECT MAX(indexed_at) AS updated_at FROM videos"),
  ]);

  return {
    stats: {
      channels: toCount(channelsCount.results?.[0]?.count),
      videos: toCount(videosCount.results?.[0]?.count),
      songs: toCount(songsCount.results?.[0]?.count),
      entries: toCount(entriesCount.results?.[0]?.count),
    },
    channels: (channelsResult.results || []).map((row) => ({
      channel_id: row.channel_id,
      channel_title: row.channel_title,
      video_count: toCount(row.video_count),
      song_count: toCount(row.song_count),
      entry_count: toCount(row.entry_count),
    })),
    updatedAt: updatedResult.results?.[0]?.updated_at || null,
  };
}

function buildSearch(query) {
  const song = requestText(query.get("song")).toLocaleLowerCase();
  const artist = requestText(query.get("artist")).toLocaleLowerCase();
  const channel = requestText(query.get("channel"));
  const where = [];
  const params = [];

  if (song) {
    where.push("g.title_search LIKE ?");
    params.push(likeValue(song));
  }
  if (artist) {
    where.push("g.artist_search LIKE ?");
    params.push(likeValue(artist));
  }
  if (channel) {
    where.push(`EXISTS (
      SELECT 1
      FROM song_entries filter_e
      JOIN videos filter_v ON filter_v.video_id = filter_e.video_id
      JOIN channels filter_c ON filter_c.channel_id = filter_v.channel_id
      WHERE filter_e.group_key = g.group_key
        AND (filter_c.channel_title LIKE ? OR filter_c.channel_id = ?)
    )`);
    params.push(likeValue(channel), channel);
  }

  return {
    song,
    artist,
    channel,
    whereSql: where.length ? `WHERE ${where.join(" AND ")}` : "",
    params,
  };
}

async function searchGroups(env, url) {
  const search = buildSearch(url.searchParams);
  const rawPage = Number.parseInt(url.searchParams.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(url.searchParams.get("pageSize") || "20", 10);
  const pageSize = Math.min(50, Math.max(1, Number.isFinite(rawPageSize) ? rawPageSize : 20));

  const countResult = await env.DB.prepare(
    `SELECT COUNT(*) AS count FROM song_groups g ${search.whereSql}`,
  ).bind(...search.params).first();
  const total = toCount(countResult?.count);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number.isFinite(rawPage) ? rawPage : 1));
  const offset = (page - 1) * pageSize;

  const defaultOrderSql = search.channel
    ? "entry_count DESC, g.song_title COLLATE NOCASE, g.artist COLLATE NOCASE, g.group_key"
    : "g.entry_count DESC, g.song_title COLLATE NOCASE, g.artist COLLATE NOCASE, g.group_key";
  let orderSql = defaultOrderSql;
  const orderParams = [];
  if (search.song) {
    orderSql = "CASE WHEN g.title_search = ? THEN 0 WHEN g.title_search LIKE ? THEN 1 ELSE 2 END, " + defaultOrderSql;
    orderParams.push(search.song, likeValue(search.song));
  } else if (search.artist) {
    orderSql = search.channel
      ? "g.song_title COLLATE NOCASE, g.artist COLLATE NOCASE, entry_count DESC, g.group_key"
      : "g.song_title COLLATE NOCASE, g.artist COLLATE NOCASE, g.entry_count DESC, g.group_key";
  }

  let groupRows = [];
  if (total > 0) {
    if (search.channel) {
      groupRows = (await env.DB.prepare(`
        SELECT
          g.group_key,
          g.song_title,
          g.artist,
          COUNT(DISTINCT scope_e.id) AS entry_count,
          COUNT(DISTINCT scope_c.channel_id) AS channel_count
        FROM song_groups g
        JOIN song_entries scope_e ON scope_e.group_key = g.group_key
        JOIN videos scope_v ON scope_v.video_id = scope_e.video_id
        JOIN channels scope_c ON scope_c.channel_id = scope_v.channel_id
        ${search.whereSql}
          AND (scope_c.channel_title LIKE ? OR scope_c.channel_id = ?)
        GROUP BY g.group_key
        ORDER BY ${orderSql}
        LIMIT ? OFFSET ?
      `).bind(
        ...search.params,
        likeValue(search.channel),
        search.channel,
        ...orderParams,
        pageSize,
        offset,
      ).all()).results || [];
    } else {
      groupRows = (await env.DB.prepare(`
        SELECT g.group_key, g.song_title, g.artist, g.entry_count, g.channel_count
        FROM song_groups g
        ${search.whereSql}
        ORDER BY ${orderSql}
        LIMIT ? OFFSET ?
      `).bind(...search.params, ...orderParams, pageSize, offset).all()).results || [];
    }
  }

  const groups = groupRows.map((row) => ({
    id: row.group_key,
    songTitle: row.song_title,
    artist: row.artist || "",
    channelCount: toCount(row.channel_count),
    entryCount: toCount(row.entry_count),
    channels: [],
  }));

  if (groups.length === 0) {
    return { groups, total, page, pageCount, pageSize };
  }

  const groupKeys = groups.map((group) => group.id);
  const placeholders = groupKeys.map(() => "?").join(",");
  const channelWhere = [`scope_e.group_key IN (${placeholders})`];
  const channelParams = [...groupKeys];
  if (search.channel) {
    channelWhere.push("(scope_c.channel_title LIKE ? OR scope_c.channel_id = ?)");
    channelParams.push(likeValue(search.channel), search.channel);
  }
  const channelRows = (await env.DB.prepare(`
    SELECT
      scope_e.group_key,
      scope_c.channel_id,
      scope_c.channel_title,
      COUNT(scope_e.id) AS entry_count
    FROM song_entries scope_e
    JOIN videos scope_v ON scope_v.video_id = scope_e.video_id
    JOIN channels scope_c ON scope_c.channel_id = scope_v.channel_id
    WHERE ${channelWhere.join(" AND ")}
    GROUP BY scope_e.group_key, scope_c.channel_id
    ORDER BY scope_e.group_key, scope_c.channel_title
  `).bind(...channelParams).all()).results || [];

  const groupsByKey = new Map(groups.map((group) => [group.id, group]));
  for (const row of channelRows) {
    const group = groupsByKey.get(row.group_key);
    if (!group) continue;
    group.channels.push({
      id: row.channel_id,
      title: row.channel_title,
      entryCount: toCount(row.entry_count),
      entries: [],
    });
  }

  for (const group of groups) {
    group.channels.sort((left, right) => right.entryCount - left.entryCount || left.title.localeCompare(right.title));
    group.channelCount = group.channels.length;
    group.entryCount = group.channels.reduce((sum, channel) => sum + channel.entryCount, 0);
  }

  return { groups, total, page, pageCount, pageSize };
}

async function searchEntries(env, url) {
  const groupKey = requestText(url.searchParams.get("groupKey"), 240);
  const channelId = requestText(url.searchParams.get("channelId"), 120);
  const rawPage = Number.parseInt(url.searchParams.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(url.searchParams.get("pageSize") || "10", 10);
  const pageSize = Math.min(50, Math.max(1, Number.isFinite(rawPageSize) ? rawPageSize : 10));

  if (!groupKey) return { ok: false, message: "缺少歌曲分组。" };

  const where = ["e.group_key = ?"];
  const params = [groupKey];
  if (channelId) {
    where.push("c.channel_id = ?");
    params.push(channelId);
  }
  const whereSql = where.join(" AND ");
  const countResult = await env.DB.prepare(`
    SELECT COUNT(*) AS count
    FROM song_entries e
    JOIN videos v ON v.video_id = e.video_id
    JOIN channels c ON c.channel_id = v.channel_id
    WHERE ${whereSql}
  `).bind(...params).first();
  const total = toCount(countResult?.count);
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number.isFinite(rawPage) ? rawPage : 1));
  const offset = (page - 1) * pageSize;
  const entries = total === 0
    ? []
    : (await env.DB.prepare(`
        SELECT
          v.title AS video_title,
          v.published_at,
          e.timestamp_text,
          e.jump_url,
          e.seconds
        FROM song_entries e
        JOIN videos v ON v.video_id = e.video_id
        JOIN channels c ON c.channel_id = v.channel_id
        WHERE ${whereSql}
        ORDER BY v.published_at DESC, e.seconds ASC, e.id ASC
        LIMIT ? OFFSET ?
      `).bind(...params, pageSize, offset).all()).results || [];

  return {
    ok: true,
    groupKey,
    channelId,
    total,
    page,
    pageCount,
    pageSize,
    entries: entries.map((row) => ({
      videoTitle: row.video_title || "",
      publishedAt: row.published_at,
      timestampText: row.timestamp_text || "",
      jumpUrl: row.jump_url || "",
    })),
  };
}

function requireSeedToken(request, env) {
  const configured = String(env.SEED_TOKEN || "");
  const supplied = request.headers.get("x-seed-token") || "";
  return Boolean(configured) && supplied === configured;
}

function required(row, key) {
  return row[key] !== undefined && row[key] !== null;
}

function seedStatements(table, rows, env, targetTable = table) {
  const statements = [];
  for (const row of rows) {
    if (table === "channels" && required(row, "channel_id") && required(row, "channel_title")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (channel_id, channel_title) VALUES (?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET channel_title = excluded.channel_title
      `).bind(row.channel_id, row.channel_title));
    } else if (table === "videos" && required(row, "video_id") && required(row, "channel_id") && required(row, "title") && required(row, "url") && required(row, "indexed_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (video_id, channel_id, title, published_at, url, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
          channel_id = excluded.channel_id,
          title = excluded.title,
          published_at = excluded.published_at,
          url = excluded.url,
          indexed_at = excluded.indexed_at
      `).bind(row.video_id, row.channel_id, row.title, row.published_at ?? null, row.url, row.indexed_at));
    } else if (table === "song_groups" && required(row, "group_key") && required(row, "song_title") && required(row, "title_search") && required(row, "artist_search") && required(row, "entry_count") && required(row, "channel_count")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(group_key) DO UPDATE SET
          song_title = excluded.song_title,
          artist = excluded.artist,
          title_search = excluded.title_search,
          artist_search = excluded.artist_search,
          entry_count = excluded.entry_count,
          channel_count = excluded.channel_count
      `).bind(row.group_key, row.song_title, row.artist ?? "", row.title_search, row.artist_search, row.entry_count, row.channel_count));
    } else if (table === "songs" && required(row, "id") && required(row, "channel_id") && required(row, "canonical_song_title") && required(row, "normalized_song_title") && required(row, "group_key") && required(row, "created_at") && required(row, "updated_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          channel_id = excluded.channel_id,
          canonical_song_title = excluded.canonical_song_title,
          normalized_song_title = excluded.normalized_song_title,
          artist = excluded.artist,
          group_key = excluded.group_key,
          created_at = excluded.created_at,
          updated_at = excluded.updated_at
      `).bind(row.id, row.channel_id, row.canonical_song_title, row.normalized_song_title, row.artist ?? "", row.group_key, row.created_at, row.updated_at));
    } else if (table === "song_entries" && required(row, "id") && required(row, "song_id") && required(row, "group_key") && required(row, "video_id") && required(row, "timestamp_text") && required(row, "seconds") && required(row, "raw_song_title") && required(row, "normalized_song_title") && required(row, "source_comment") && required(row, "jump_url") && required(row, "created_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO ${targetTable} (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
      `).bind(row.id, row.song_id, row.group_key, row.video_id, row.timestamp_text, row.seconds, row.raw_song_title, row.normalized_song_title, row.source_comment, row.jump_url, row.created_at));
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
      CREATE TABLE IF NOT EXISTS snapshot_channels (
        channel_id TEXT PRIMARY KEY NOT NULL,
        channel_title TEXT NOT NULL
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_videos (
        video_id TEXT PRIMARY KEY NOT NULL,
        channel_id TEXT NOT NULL,
        title TEXT NOT NULL,
        published_at TEXT,
        url TEXT NOT NULL,
        indexed_at TEXT NOT NULL
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_song_groups (
        group_key TEXT PRIMARY KEY NOT NULL,
        song_title TEXT NOT NULL,
        artist TEXT NOT NULL,
        title_search TEXT NOT NULL,
        artist_search TEXT NOT NULL,
        entry_count INTEGER NOT NULL,
        channel_count INTEGER NOT NULL
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_songs (
        id INTEGER PRIMARY KEY NOT NULL,
        channel_id TEXT NOT NULL,
        canonical_song_title TEXT NOT NULL,
        normalized_song_title TEXT NOT NULL,
        artist TEXT NOT NULL,
        group_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `),
    env.DB.prepare(`
      CREATE TABLE IF NOT EXISTS snapshot_song_entries (
        id INTEGER PRIMARY KEY NOT NULL,
        song_id INTEGER NOT NULL,
        group_key TEXT NOT NULL,
        video_id TEXT NOT NULL,
        timestamp_text TEXT NOT NULL,
        seconds INTEGER NOT NULL,
        raw_song_title TEXT NOT NULL,
        normalized_song_title TEXT NOT NULL,
        source_comment TEXT NOT NULL,
        jump_url TEXT NOT NULL,
        created_at TEXT NOT NULL
      )
    `),
  ];
}

async function snapshotState(env, version) {
  const row = await env.DB.prepare(
    "SELECT version, status, expected_json FROM dataset_meta WHERE id = 1",
  ).first();
  if (!row || row.version !== version || row.status !== "loading") return null;
  return row;
}

async function snapshotCountsMatch(env, state) {
  let expected;
  try {
    expected = snapshotExpectedTables(JSON.parse(state.expected_json || "{}"));
  } catch {
    return false;
  }
  const tables = [...SEED_TABLES];
  const counts = await env.DB.batch(
    tables.map((table) =>
      env.DB.prepare(`SELECT COUNT(*) AS row_count FROM ${SNAPSHOT_STAGING_TABLES[table]}`),
    ),
  );
  return tables.every((table, index) => {
    const count = Number(counts[index]?.results?.[0]?.row_count);
    return Number.isSafeInteger(count) && count === expected[table];
  });
}

async function startSnapshot(request, env) {
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
    await env.DB.batch([
      ...snapshotSchemaStatements(env),
      env.DB.prepare("DELETE FROM snapshot_song_entries"),
      env.DB.prepare("DELETE FROM snapshot_songs"),
      env.DB.prepare("DELETE FROM snapshot_song_groups"),
      env.DB.prepare("DELETE FROM snapshot_videos"),
      env.DB.prepare("DELETE FROM snapshot_channels"),
      env.DB.prepare(`
        INSERT INTO dataset_meta (id, version, status, expected_json, updated_at)
        VALUES (1, ?, 'loading', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET
          version = excluded.version,
          status = excluded.status,
          expected_json = excluded.expected_json,
          updated_at = excluded.updated_at
      `).bind(version, JSON.stringify(expectedTables)),
    ]);
    return json({ ok: true, version, status: "loading" });
  } catch (error) {
    console.error("snapshot start failed", error);
    return json({ ok: false, message: "Snapshot start failed" }, 500);
  }
}

async function commitSnapshot(request, env) {
  if (!requireSeedToken(request, env)) return json({ ok: false, message: "Not found" }, 404);
  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, message: "Invalid JSON" }, 400);
  }
  const version = requestText(payload?.version, 120);
  if (!version) return json({ ok: false, message: "Missing snapshot version" }, 400);
  const state = await snapshotState(env, version);
  if (!state) {
    return json({ ok: false, message: "Snapshot is not ready for commit" }, 409);
  }

  try {
    if (!(await snapshotCountsMatch(env, state))) {
      return json({ ok: false, message: "Snapshot is incomplete; live data was kept" }, 409);
    }
    await env.DB.batch([
      env.DB.prepare("DELETE FROM song_entries"),
      env.DB.prepare("DELETE FROM songs"),
      env.DB.prepare("DELETE FROM song_groups"),
      env.DB.prepare("DELETE FROM videos"),
      env.DB.prepare("DELETE FROM channels"),
      env.DB.prepare("INSERT INTO channels SELECT channel_id, channel_title FROM snapshot_channels"),
      env.DB.prepare("INSERT INTO videos SELECT video_id, channel_id, title, published_at, url, indexed_at FROM snapshot_videos"),
      env.DB.prepare("INSERT INTO song_groups SELECT group_key, song_title, artist, title_search, artist_search, entry_count, channel_count FROM snapshot_song_groups"),
      env.DB.prepare("INSERT INTO songs SELECT id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at FROM snapshot_songs"),
      env.DB.prepare("INSERT INTO song_entries SELECT id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at FROM snapshot_song_entries"),
      env.DB.prepare(`
        UPDATE dataset_meta
        SET status = 'ready', updated_at = CURRENT_TIMESTAMP
        WHERE id = 1 AND version = ?
      `).bind(version),
    ]);
    return json({ ok: true, version, status: "ready" });
  } catch (error) {
    console.error("snapshot commit failed", error);
    return json({ ok: false, message: "Snapshot commit failed; previous data was kept" }, 500);
  }
}

async function seed(request, env) {
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
    const targetTable = SNAPSHOT_STAGING_TABLES[table];
    await env.DB.batch(seedStatements(table, rows, env, targetTable));
    return json({ ok: true, table, inserted: rows.length, version });
  } catch (error) {
    console.error("seed failed", table, error);
    return json({ ok: false, message: "Seed batch failed" }, 500);
  }
}

async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (request.method === "GET" && (path === "/" || path === "/index.html")) {
    return textResponse(pageHtml, "text/html; charset=utf-8");
  }
  if (request.method === "GET" && path === "/styles.css") {
    return textResponse(stylesCss, "text/css; charset=utf-8", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/app.js") {
    return textResponse(clientJs, "text/javascript; charset=utf-8", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/favicon.svg") {
    return textResponse(faviconSvg, "image/svg+xml", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/api/overview") {
    try {
      return json(await queryOverview(env));
    } catch (error) {
      console.error("overview failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "GET" && path === "/api/search") {
    try {
      return json(await searchGroups(env, url));
    } catch (error) {
      console.error("search failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "GET" && path === "/api/entries") {
    try {
      const result = await searchEntries(env, url);
      return json(result, result.ok === false ? 400 : 200);
    } catch (error) {
      console.error("entries failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "POST" && path === "/api/admin/snapshot/start") {
    return startSnapshot(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/snapshot/commit") {
    return commitSnapshot(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/seed") {
    return seed(request, env);
  }
  return json({ ok: false, message: "Not found" }, 404);
}

export default {
  async fetch(request, env) {
    return handle(request, env);
  },
};
