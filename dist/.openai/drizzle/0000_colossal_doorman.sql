CREATE TABLE `channels` (
	`channel_id` text PRIMARY KEY NOT NULL,
	`channel_title` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `song_entries` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`song_id` integer NOT NULL,
	`video_id` text NOT NULL,
	`timestamp_text` text NOT NULL,
	`seconds` integer NOT NULL,
	`raw_song_title` text NOT NULL,
	`normalized_song_title` text NOT NULL,
	`source_comment` text NOT NULL,
	`jump_url` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`song_id`) REFERENCES `songs`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`video_id`) REFERENCES `videos`(`video_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_song_entries_song_id` ON `song_entries` (`song_id`);--> statement-breakpoint
CREATE INDEX `idx_song_entries_video_id` ON `song_entries` (`video_id`);--> statement-breakpoint
CREATE INDEX `idx_song_entries_normalized` ON `song_entries` (`normalized_song_title`);--> statement-breakpoint
CREATE UNIQUE INDEX `song_entries_video_seconds_normalized_unique` ON `song_entries` (`video_id`,`seconds`,`normalized_song_title`);--> statement-breakpoint
CREATE TABLE `song_groups` (
	`group_key` text PRIMARY KEY NOT NULL,
	`song_title` text NOT NULL,
	`artist` text DEFAULT '' NOT NULL,
	`title_search` text NOT NULL,
	`artist_search` text NOT NULL,
	`entry_count` integer DEFAULT 0 NOT NULL,
	`channel_count` integer DEFAULT 0 NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_song_groups_title_search` ON `song_groups` (`title_search`);--> statement-breakpoint
CREATE INDEX `idx_song_groups_artist_search` ON `song_groups` (`artist_search`);--> statement-breakpoint
CREATE TABLE `songs` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`channel_id` text NOT NULL,
	`canonical_song_title` text NOT NULL,
	`normalized_song_title` text NOT NULL,
	`artist` text DEFAULT '' NOT NULL,
	`group_key` text NOT NULL,
	`created_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`channel_id`) REFERENCES `channels`(`channel_id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`group_key`) REFERENCES `song_groups`(`group_key`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_songs_channel_normalized` ON `songs` (`channel_id`,`normalized_song_title`);--> statement-breakpoint
CREATE INDEX `idx_songs_group_key` ON `songs` (`group_key`);--> statement-breakpoint
CREATE UNIQUE INDEX `songs_channel_normalized_unique` ON `songs` (`channel_id`,`normalized_song_title`);--> statement-breakpoint
CREATE TABLE `videos` (
	`video_id` text PRIMARY KEY NOT NULL,
	`channel_id` text NOT NULL,
	`title` text NOT NULL,
	`published_at` text,
	`url` text NOT NULL,
	`indexed_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL,
	FOREIGN KEY (`channel_id`) REFERENCES `channels`(`channel_id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `idx_videos_published_at` ON `videos` (`published_at`);--> statement-breakpoint
CREATE INDEX `idx_videos_channel_published` ON `videos` (`channel_id`,`published_at`);