import { requestText } from "./http.js";

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
  // Match song_identity.ARTIST_TOKEN_RE: spaces inside one artist's name
  // are significant, and collaboration words must have word boundaries.
  // Unicode boundaries also avoid splitting these words inside CJK names.
  return String(value ?? "")
    .split(/\s*(?:×|[&＆]|・|[＋+]|\s+[xX]\s+|(?<![\p{L}\p{N}_])w\s*[/／]\s*|(?<![\p{L}\p{N}_])(?:feat\.?|ft\.?|with|and|covered\s+by|cover\s+by)(?![\p{L}\p{N}_])|[/／])\s*/iu)
    .map((part) => compactKey(part))
    .filter(Boolean);
}

function artistMatches(row, search, scoped = false) {
  if (!search.artist) return true;
  const source = scoped
    ? row.scope_artist
    : row.artist_search || row.artist;
  // Only the legacy group-level artist_search contains space-separated keys;
  // songs.artist contains a full artist name or a collaboration credit.
  const keys = [...new Set(scoped || !row.artist_search
    ? artistKeysFromText(source)
    : String(source ?? "").split(/\s+/u).filter(Boolean))];
  if (keys.includes(search.artist)) return true;
  if (isShortAsciiKey(search.artist)) return false;
  return keys.some((key) => search.artist.includes(key) || key.includes(search.artist));
}

function toCount(value) {
  return Number(value || 0);
}

export async function queryOverview(env) {
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

export async function searchGroups(env, url) {
  const search = buildSearch(url.searchParams);
  const exactChannel = search.channel
    ? await env.DB.prepare("SELECT channel_id FROM channels WHERE channel_id = ?").bind(search.channel).first()
    : null;
  const channelClause = exactChannel ? "scope_c.channel_id = ?" : "scope_c.channel_title LIKE ? ESCAPE '\\'";
  const channelParams = search.channel ? [exactChannel ? search.channel : likeValue(search.channel)] : [];
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
        ${search.channel ? `${search.whereSql ? "AND" : "WHERE"} ${channelClause}` : ""}
        GROUP BY g.group_key, g.song_title, g.artist, g.title_search, g.artist_search,
                 scope_c.channel_id, scope_c.channel_title, scope_s.id, scope_s.artist
      `).bind(
        ...search.params,
        ...channelParams,
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
    if (aggregate) {
      group.channels = [...group.scopedChannels.values()].map((channel) => ({ ...channel, entries: [] }));
    }
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

  // The scoped aggregate already contains the accepted per-channel counts.
  // Reuse it, avoiding a second scan (and inconsistent counts during a sync).
  if (aggregate) {
    for (const group of pagedGroups) {
      group.channels.sort((left, right) => right.entryCount - left.entryCount || compareText(left.title, right.title));
      delete group.scopedChannelId;
      delete group.channelTitle;
      delete group.searchRow;
    }
    return { groups: pagedGroups, total, page, pageCount, pageSize };
  }

  const groupKeys = pagedGroups.map((group) => group.id);
  const placeholders = groupKeys.map(() => "?").join(",");
  const channelWhere = [`scope_e.group_key IN (${placeholders})`];
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
    GROUP BY scope_e.group_key, scope_c.channel_id, scope_c.channel_title
    ORDER BY scope_e.group_key, scope_c.channel_title
  `).bind(...groupKeys).all()).results || [];

  const groupsById = new Map(pagedGroups.map((group) => [group.id, group]));
  for (const row of channelRows) {
    const group = groupsById.get(row.group_key);
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
    delete group.scopedChannelId;
    delete group.channelTitle;
    delete group.searchRow;
  }

  return { groups: pagedGroups, total, page, pageCount, pageSize };
}

export async function searchEntries(env, url) {
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
      `SELECT id, artist FROM songs WHERE group_key = ?${channelId ? " AND channel_id = ?" : ""}`,
    ).bind(groupKey, ...(channelId ? [channelId] : [])).all()).results || [];
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
