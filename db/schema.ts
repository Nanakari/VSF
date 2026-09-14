import { sql } from "drizzle-orm";
import {
  index,
  integer,
  sqliteTable,
  text,
  unique,
} from "drizzle-orm/sqlite-core";

export const channels = sqliteTable("channels", {
  channelId: text("channel_id").primaryKey(),
  channelTitle: text("channel_title").notNull(),
});

export const datasetMeta = sqliteTable("dataset_meta", {
  id: integer("id").primaryKey().default(1),
  version: text("version").notNull(),
  status: text("status").notNull(),
  expectedJson: text("expected_json").notNull().default("{}"),
  updatedAt: text("updated_at")
    .notNull()
    .default(sql`CURRENT_TIMESTAMP`),
});

export const videos = sqliteTable(
  "videos",
  {
    videoId: text("video_id").primaryKey(),
    channelId: text("channel_id")
      .notNull()
      .references(() => channels.channelId),
    title: text("title").notNull(),
    publishedAt: text("published_at"),
    url: text("url").notNull(),
    indexedAt: text("indexed_at")
      .notNull()
      .default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    index("idx_videos_published_at").on(table.publishedAt),
    index("idx_videos_channel_published").on(table.channelId, table.publishedAt),
  ],
);

export const songGroups = sqliteTable(
  "song_groups",
  {
    groupKey: text("group_key").primaryKey(),
    songTitle: text("song_title").notNull(),
    artist: text("artist").notNull().default(""),
    titleSearch: text("title_search").notNull(),
    artistSearch: text("artist_search").notNull(),
    entryCount: integer("entry_count").notNull().default(0),
    channelCount: integer("channel_count").notNull().default(0),
  },
  (table) => [
    index("idx_song_groups_title_search").on(table.titleSearch),
    index("idx_song_groups_artist_search").on(table.artistSearch),
  ],
);

export const songs = sqliteTable(
  "songs",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    channelId: text("channel_id")
      .notNull()
      .references(() => channels.channelId),
    canonicalSongTitle: text("canonical_song_title").notNull(),
    normalizedSongTitle: text("normalized_song_title").notNull(),
    artist: text("artist").notNull().default(""),
    groupKey: text("group_key")
      .notNull()
      .references(() => songGroups.groupKey),
    createdAt: text("created_at")
      .notNull()
      .default(sql`CURRENT_TIMESTAMP`),
    updatedAt: text("updated_at")
      .notNull()
      .default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    unique("songs_channel_normalized_unique").on(table.channelId, table.normalizedSongTitle),
    index("idx_songs_channel_normalized").on(table.channelId, table.normalizedSongTitle),
    index("idx_songs_group_key").on(table.groupKey),
  ],
);

export const songEntries = sqliteTable(
  "song_entries",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    songId: integer("song_id")
      .notNull()
      .references(() => songs.id),
    groupKey: text("group_key")
      .notNull()
      .references(() => songGroups.groupKey),
    videoId: text("video_id")
      .notNull()
      .references(() => videos.videoId),
    timestampText: text("timestamp_text").notNull(),
    seconds: integer("seconds").notNull(),
    rawSongTitle: text("raw_song_title").notNull(),
    normalizedSongTitle: text("normalized_song_title").notNull(),
    sourceComment: text("source_comment").notNull(),
    jumpUrl: text("jump_url").notNull(),
    createdAt: text("created_at")
      .notNull()
      .default(sql`CURRENT_TIMESTAMP`),
  },
  (table) => [
    unique("song_entries_video_seconds_normalized_unique").on(table.videoId, table.seconds, table.normalizedSongTitle),
    index("idx_song_entries_group_key").on(table.groupKey),
    index("idx_song_entries_song_id").on(table.songId),
    index("idx_song_entries_video_id").on(table.videoId),
    index("idx_song_entries_normalized").on(table.normalizedSongTitle),
  ],
);
