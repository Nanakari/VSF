const pageHtml = "__SITE_HTML__";
const stylesCss = "__SITE_CSS__";
const clientJs = "__SITE_JS__";
const faviconSvg = "__SITE_FAVICON__";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

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

  let orderSql = "g.entry_count DESC, g.song_title COLLATE NOCASE, g.artist COLLATE NOCASE, g.group_key";
  const orderParams = [];
  if (search.song) {
    orderSql = "CASE WHEN g.title_search = ? THEN 0 WHEN g.title_search LIKE ? THEN 1 ELSE 2 END, " + orderSql;
    orderParams.push(search.song, likeValue(search.song));
  } else if (search.artist) {
    orderSql = "g.song_title COLLATE NOCASE, g.artist COLLATE NOCASE, g.entry_count DESC, g.group_key";
  }

  const groupRows = total === 0
    ? []
    : (await env.DB.prepare(`
        SELECT g.group_key, g.song_title, g.artist, g.entry_count, g.channel_count
        FROM song_groups g
        ${search.whereSql}
        ORDER BY ${orderSql}
        LIMIT ? OFFSET ?
      `).bind(...search.params, ...orderParams, pageSize, offset).all()).results || [];

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
  const detailWhere = [`g.group_key IN (${placeholders})`];
  const detailParams = [...groupKeys];
  if (search.channel) {
    detailWhere.push("(c.channel_title LIKE ? OR c.channel_id = ?)");
    detailParams.push(likeValue(search.channel), search.channel);
  }
  const detailRows = (await env.DB.prepare(`
    SELECT
      g.group_key,
      c.channel_id,
      c.channel_title,
      v.title AS video_title,
      v.published_at,
      e.timestamp_text,
      e.jump_url,
      e.seconds
    FROM song_entries e
    JOIN song_groups g ON g.group_key = e.group_key
    JOIN videos v ON v.video_id = e.video_id
    JOIN channels c ON c.channel_id = v.channel_id
    WHERE ${detailWhere.join(" AND ")}
    ORDER BY g.group_key, c.channel_title, v.published_at DESC, e.seconds ASC
  `).bind(...detailParams).all()).results || [];

  const groupsByKey = new Map(groups.map((group) => [group.id, group]));
  for (const row of detailRows) {
    const group = groupsByKey.get(row.group_key);
    if (!group) continue;
    let channel = group.channels.find((item) => item.id === row.channel_id);
    if (!channel) {
      channel = { id: row.channel_id, title: row.channel_title, entries: [] };
      group.channels.push(channel);
    }
    channel.entries.push({
      videoTitle: row.video_title || "",
      publishedAt: row.published_at,
      timestampText: row.timestamp_text || "",
      jumpUrl: row.jump_url || "",
    });
  }

  for (const group of groups) {
    group.channels.sort((left, right) => right.entries.length - left.entries.length || left.title.localeCompare(right.title));
    if (search.channel) {
      group.channelCount = group.channels.length;
      group.entryCount = group.channels.reduce((sum, channel) => sum + channel.entries.length, 0);
    }
  }

  return { groups, total, page, pageCount, pageSize };
}

function requireSeedToken(request, env) {
  const configured = String(env.SEED_TOKEN || "");
  const supplied = request.headers.get("x-seed-token") || "";
  return Boolean(configured) && supplied === configured;
}

function required(row, key) {
  return row[key] !== undefined && row[key] !== null;
}

function seedStatements(table, rows, env) {
  const statements = [];
  for (const row of rows) {
    if (table === "channels" && required(row, "channel_id") && required(row, "channel_title")) {
      statements.push(env.DB.prepare(`
        INSERT INTO channels (channel_id, channel_title) VALUES (?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET channel_title = excluded.channel_title
      `).bind(row.channel_id, row.channel_title));
    } else if (table === "videos" && required(row, "video_id") && required(row, "channel_id") && required(row, "title") && required(row, "url") && required(row, "indexed_at")) {
      statements.push(env.DB.prepare(`
        INSERT INTO videos (video_id, channel_id, title, published_at, url, indexed_at)
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
        INSERT INTO song_groups (group_key, song_title, artist, title_search, artist_search, entry_count, channel_count)
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
        INSERT INTO songs (id, channel_id, canonical_song_title, normalized_song_title, artist, group_key, created_at, updated_at)
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
        INSERT INTO song_entries (id, song_id, group_key, video_id, timestamp_text, seconds, raw_song_title, normalized_song_title, source_comment, jump_url, created_at)
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
  const allowed = new Set(["channels", "videos", "song_groups", "songs", "song_entries"]);
  if (!allowed.has(table) || !Array.isArray(rows) || rows.length === 0 || rows.length > 90) {
    return json({ ok: false, message: "Invalid seed batch" }, 400);
  }
  try {
    await env.DB.batch(seedStatements(table, rows, env));
    return json({ ok: true, table, inserted: rows.length });
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
