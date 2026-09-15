const pageHtml = "__SITE_HTML__";
const stylesCss = "__SITE_CSS__";
const clientJs = "__SITE_JS__";
const faviconSvg = "__SITE_FAVICON__";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

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

function foldSearchText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replaceAll("ß", "ss")
    .replaceAll("ς", "σ");
}

function likeValue(value) {
  return `%${String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("%", "\\%")
    .replaceAll("_", "\\_")}%`;
}

function normalizeSearchText(value) {
  return foldSearchText(
    String(value ?? "")
      .replace(/\u3000/g, " ")
      .replace(/\s+/gu, " ")
      .trim(),
  );
}

function compactKey(value) {
  return normalizeSearchText(value).replace(/[^\p{L}\p{N}]+/gu, "");
}

function isShortAsciiKey(value) {
  return value.length <= 4 && /^[A-Za-z0-9]+$/u.test(value);
}

function compareText(left, right) {
  // Python's ``casefold`` ordering is a code-point ordering, while
  // ``localeCompare`` varies with the Worker locale.  Keep the comparison
  // deterministic across local Node tests and Cloudflare Workers.
  const fold = foldSearchText;
  const a = fold(left);
  const b = fold(right);
  return a < b ? -1 : a > b ? 1 : 0;
}

function levenshteinAtMost(left, right, maxDistance = 2) {
  if (Math.abs(left.length - right.length) > maxDistance) return maxDistance + 1;
  if (left.length > right.length) return levenshteinAtMost(right, left, maxDistance);
  let previous = Array.from({ length: left.length + 1 }, (_, index) => index);
  for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
    const current = [rightIndex];
    let rowMin = current[0];
    for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
      const value = Math.min(
        current[leftIndex - 1] + 1,
        previous[leftIndex] + 1,
        previous[leftIndex - 1] + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1),
      );
      current.push(value);
      rowMin = Math.min(rowMin, value);
    }
    if (rowMin > maxDistance) return maxDistance + 1;
    previous = current;
  }
  return previous[previous.length - 1];
}

function similarSongKey(left, right) {
  if (left === right) return true;
  if (Math.min(left.length, right.length) < 6) return false;
  const distance = levenshteinAtMost(left, right, 2);
  return distance <= 1 || (distance <= 2 && Math.min(left.length, right.length) >= 9);
}

function titleKeys(row) {
  const keys = new Set(compactTitleAliases(row));
  const titleKey = compactKey(row.song_title);
  if (titleKey) keys.add(titleKey);
  return [...keys];
}

function normalizedTitleKeys(row) {
  const searchText = String(row.title_search ?? "");
  try {
    const payload = JSON.parse(searchText);
    if (Array.isArray(payload?.normalized)) {
      return payload.normalized.map((value) => normalizeSearchText(value)).filter(Boolean);
    }
  } catch (_) {
    const aliases = searchText.match(/\^([^\^]+)\^/gu) || [];
    if (aliases.length > 0) return aliases.map((token) => token.slice(1, -1));
  }
  const fallback = normalizeSearchText(row.song_title);
  return fallback ? [fallback] : [];
}

function compactTitleAliases(row) {
  const searchText = String(row.title_search ?? "");
  try {
    const payload = JSON.parse(searchText);
    if (Array.isArray(payload?.compact)) {
      return payload.compact.map((value) => compactKey(value)).filter(Boolean);
    }
  } catch (_) {
    const aliases = searchText.match(/~([^~]+)~/gu) || [];
    if (aliases.length > 0) return aliases.map((token) => token.slice(1, -1));
  }
  return [];
}

function realTitleText(row) {
  return normalizedTitleKeys(row).join(" ");
}

function songMatches(row, search) {
  if (!search.song) return true;
  const queryKey = search.songKey;
  if (!queryKey) return normalizedTitleKeys(row).some((title) => title.includes(search.song));
  if (isShortAsciiKey(queryKey)) {
    return titleKeys(row).some((titleKey) => (
      titleKey === queryKey
      || titleKey.startsWith(queryKey)
      || similarSongKey(titleKey, queryKey)
    ));
  }
  if (normalizedTitleKeys(row).some((title) => title.includes(search.song))) return true;
  return titleKeys(row).some((titleKey) => (
    titleKey === queryKey
    || titleKey.startsWith(queryKey)
    || titleKey.includes(queryKey)
    || queryKey.includes(titleKey)
    || similarSongKey(titleKey, queryKey)
  ));
}

function songRelevance(row, search) {
  if (!search.song) return 5;
  const queryKey = search.songKey;
  if (!queryKey) return normalizedSearchInRow(row, search.song) ? 4 : 5;
  const keys = titleKeys(row);
  if (keys.includes(queryKey)) return 0;
  if (keys.some((key) => key.startsWith(queryKey))) return 1;
  if (keys.some((key) => key.includes(queryKey))) return 2;
  if (keys.some((key) => similarSongKey(key, queryKey))) return 3;
  return normalizedSearchInRow(row, search.song) ? 4 : 5;
}

function normalizedSearchInRow(row, query) {
  return realTitleText(row).includes(query);
}

function artistKeysFromText(value) {
  return String(value ?? "")
    .split(/\s*(?:\/|／|\||｜|&|＆|×|\+|w\s*\/|feat\.?|ft\.?|with|and)\s*/iu)
    .map((part) => compactKey(part))
    .filter(Boolean);
}

function artistMatches(row, search, scoped = false) {
  if (!search.artist) return true;
  const source = scoped
    ? row.scope_artist
    : row.artist_search || row.artist;
  const keys = [...new Set(
    String(source ?? "")
      .split(/\s+/u)
      .flatMap((part) => artistKeysFromText(part)),
  )];
  if (keys.includes(search.artist)) return true;
  if (isShortAsciiKey(search.artist)) return false;
  return keys.some((key) => search.artist.includes(key) || key.includes(search.artist));
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
  const song = normalizeSearchText(requestText(query.get("song")));
  const songKey = compactKey(song);
  const artistInput = requestText(query.get("artist"));
  const artist = compactKey(artistInput);
  const channel = requestText(query.get("channel"));
  const where = [];
  const params = [];

  if (artistInput && !artist) {
    where.push("0 = 1");
  }

  return {
    song,
    songKey,
    artist,
    artistInput,
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

  const aggregate = Boolean(search.channel || search.artist);
  const groupRows = aggregate
    ? (await env.DB.prepare(`
        SELECT
          g.group_key,
          g.song_title,
          g.artist,
          g.title_search,
          g.artist_search,
          scope_c.channel_id,
          scope_c.channel_title,
          scope_s.id AS song_id,
          scope_s.artist AS scope_artist,
          COUNT(scope_e.id) AS entry_count
        FROM song_groups g
        JOIN song_entries scope_e ON scope_e.group_key = g.group_key
        JOIN songs scope_s ON scope_s.id = scope_e.song_id
        JOIN videos scope_v ON scope_v.video_id = scope_e.video_id
        JOIN channels scope_c ON scope_c.channel_id = scope_v.channel_id
        ${search.whereSql}
        ${search.channel ? `${search.whereSql ? "AND" : "WHERE"} (scope_c.channel_title LIKE ? ESCAPE '\\' OR scope_c.channel_id = ?)` : ""}
        GROUP BY g.group_key, g.song_title, g.artist, g.title_search, g.artist_search,
                 scope_c.channel_id, scope_c.channel_title, scope_s.id, scope_s.artist
      `).bind(
        ...search.params,
        ...(search.channel ? [likeValue(search.channel), search.channel] : []),
      ).all()).results || []
    : (await env.DB.prepare(`
      SELECT g.group_key, g.song_title, g.artist, g.title_search,
               g.entry_count, g.channel_count
        FROM song_groups g
        ${search.whereSql}
      `).bind(...search.params).all()).results || [];

  const groupsByKey = new Map();
  for (const row of groupRows) {
    if (!songMatches(row, search)) continue;
    // Aggregate rows are split by song so author filtering can happen in JS
    // against the real D1 ``songs.artist`` column.  This keeps unknown-author
    // entries from leaking into a matched channel and avoids the nonexistent
    // per-song artist-search column.
    if (aggregate && search.artist && !artistMatches(row, search, true)) continue;
    const scopedKey = search.channel
      ? `${row.group_key}\u0000${row.channel_id || ""}`
      : row.group_key;
    let group = groupsByKey.get(scopedKey);
    if (!group) {
      group = {
        id: row.group_key,
        songTitle: row.song_title,
        artist: row.artist || "",
        channelCount: 0,
        entryCount: 0,
        channels: [],
        scopedChannelId: search.channel ? row.channel_id || "" : "",
        channelTitle: search.channel ? row.channel_title || "" : "",
        searchRow: row,
        scopedChannels: new Map(),
      };
      groupsByKey.set(scopedKey, group);
    }
    group.entryCount += toCount(row.entry_count);
    const channelKey = row.channel_id || "";
    if (aggregate) {
      const scopedChannel = group.scopedChannels.get(channelKey) || {
        id: channelKey,
        title: row.channel_title || "",
        entryCount: 0,
      };
      scopedChannel.entryCount += toCount(row.entry_count);
      group.scopedChannels.set(channelKey, scopedChannel);
    }
  }
  const groups = [...groupsByKey.values()];
  for (const group of groups) {
    group.channelCount = aggregate
      ? group.scopedChannels.size
      : toCount(group.searchRow.channel_count);
    delete group.scopedChannels;
  }

  groups.sort((left, right) => {
    if (search.song) {
      return songRelevance(left.searchRow, search)
        - songRelevance(right.searchRow, search)
        || compareText(left.songTitle, right.songTitle)
        || compareText(left.artist, right.artist)
        || compareText(left.channelTitle, right.channelTitle)
        || compareText(left.id, right.id);
    }
    if (search.artist) {
      return compareText(left.songTitle, right.songTitle)
        || compareText(left.artist, right.artist)
        || compareText(left.channelTitle, right.channelTitle)
        || (right.entryCount - left.entryCount)
        || compareText(left.id, right.id);
    }
    return (right.entryCount - left.entryCount)
      || compareText(left.channelTitle, right.channelTitle)
      || compareText(left.songTitle, right.songTitle)
      || compareText(left.artist, right.artist)
      || compareText(left.id, right.id);
  });

  const total = groups.length;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pageCount, Math.max(1, Number.isFinite(rawPage) ? rawPage : 1));
  const offset = (page - 1) * pageSize;
  const pagedGroups = groups.slice(offset, offset + pageSize);

  if (pagedGroups.length === 0) {
    return { groups: pagedGroups, total, page, pageCount, pageSize };
  }

  const groupKeys = pagedGroups.map((group) => group.id);
  const placeholders = groupKeys.map(() => "?").join(",");
  const channelWhere = [`scope_e.group_key IN (${placeholders})`];
  const channelParams = [...groupKeys];
  if (search.channel) {
    channelWhere.push("(scope_c.channel_title LIKE ? ESCAPE '\\' OR scope_c.channel_id = ?)");
    channelParams.push(likeValue(search.channel), search.channel);
  }
  const channelRows = (await env.DB.prepare(`
    SELECT
      scope_e.group_key,
      scope_c.channel_id,
      scope_c.channel_title,
      scope_s.id AS song_id,
      scope_s.artist AS scope_artist,
      COUNT(scope_e.id) AS entry_count
    FROM song_entries scope_e
    JOIN songs scope_s ON scope_s.id = scope_e.song_id
    JOIN videos scope_v ON scope_v.video_id = scope_e.video_id
    JOIN channels scope_c ON scope_c.channel_id = scope_v.channel_id
    WHERE ${channelWhere.join(" AND ")}
    GROUP BY scope_e.group_key, scope_c.channel_id, scope_c.channel_title,
             scope_s.id, scope_s.artist
    ORDER BY scope_e.group_key, scope_c.channel_title
  `).bind(...channelParams).all()).results || [];

  const groupsByScopedKey = new Map(
    pagedGroups.map((group) => [
      `${group.id}\u0000${group.scopedChannelId}`,
      group,
    ]),
  );
  for (const row of channelRows) {
    if (search.artist && !artistMatches(row, search, true)) continue;
    const group = groupsByScopedKey.get(
      `${row.group_key}\u0000${search.channel ? row.channel_id : ""}`,
    );
    if (!group) continue;
    const existing = group.channels.find((channel) => channel.id === row.channel_id);
    if (existing) {
      existing.entryCount += toCount(row.entry_count);
    } else {
      group.channels.push({
        id: row.channel_id,
        title: row.channel_title,
        entryCount: toCount(row.entry_count),
        entries: [],
      });
    }
  }

  for (const group of pagedGroups) {
    group.channels.sort((left, right) => right.entryCount - left.entryCount || compareText(left.title, right.title));
    if (aggregate) {
      group.channelCount = group.channels.length;
      group.entryCount = group.channels.reduce((sum, channel) => sum + channel.entryCount, 0);
    }
    delete group.scopedChannelId;
    delete group.channelTitle;
    delete group.searchRow;
  }

  return { groups: pagedGroups, total, page, pageCount, pageSize };
}

async function searchEntries(env, url) {
  const groupKey = requestText(url.searchParams.get("groupKey"), 240);
  const channelId = requestText(url.searchParams.get("channelId"), 120);
  const artistInput = requestText(url.searchParams.get("artist"));
  const artist = compactKey(artistInput);
  const rawPage = Number.parseInt(url.searchParams.get("page") || "1", 10);
  const rawPageSize = Number.parseInt(url.searchParams.get("pageSize") || "10", 10);
  const pageSize = Math.min(50, Math.max(1, Number.isFinite(rawPageSize) ? rawPageSize : 10));

  if (!groupKey) return { ok: false, message: "缺少歌曲分组。" };

  let songIds = null;
  if (artistInput && !artist) {
    songIds = [];
  } else if (artist) {
    // D1's ``songs`` table contains the source artist text but deliberately
    // has no derived per-song artist-search column.  Fetch only the small song metadata set,
    // filter it with the shared JS matcher, then use the accepted IDs for the
    // count and paged entry query.
    const songRows = (await env.DB.prepare(
      "SELECT id, artist FROM songs WHERE group_key = ?",
    ).bind(groupKey).all()).results || [];
    songIds = songRows
      .filter((row) => artistMatches({ scope_artist: row.artist }, { artist }, true))
      .map((row) => Number(row.id))
      .filter((id) => Number.isSafeInteger(id));
  }

  const where = ["e.group_key = ?"];
  const params = [groupKey];
  if (channelId) {
    where.push("c.channel_id = ?");
    params.push(channelId);
  }
  if (songIds !== null) {
    if (songIds.length === 0) {
      return {
        ok: true,
        groupKey,
        channelId,
        total: 0,
        page: 1,
        pageCount: 1,
        pageSize,
        entries: [],
      };
    }
    // Keep this to one D1 bind even when a merged group has many per-channel
    // song rows; D1 rejects requests that exceed its bind-variable limit.
    where.push("e.song_id IN (SELECT value FROM json_each(?))");
    params.push(JSON.stringify(songIds));
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
  ];
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
