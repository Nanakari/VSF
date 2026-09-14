CREATE TABLE `dataset_meta` (
	`id` integer PRIMARY KEY DEFAULT 1 NOT NULL,
	`version` text NOT NULL,
	`status` text NOT NULL,
	`updated_at` text DEFAULT CURRENT_TIMESTAMP NOT NULL
);
