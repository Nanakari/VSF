# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- Reject untrusted Host headers before issuing local sessions, and reject cross-origin browser management writes in both local applications.
- Keep credentials out of network failure messages and exception chains; redact credentials echoed by YouTube and site sync error responses.
- Leave optional site sync configuration empty by default so a fresh local installation does not contact a placeholder site.

## [0.3.2] - 2026-10-11

- Wait a full idle grace period after the last browser page closes, preventing frozen Windows apps from exiting during search navigation or reloads.
- Add portable lifecycle regressions for page transitions, multiple tabs, and active indexing jobs; rebuild and verify both Windows executables.
- Reject reverse substring song matches so long queries do not incorrectly return short titles such as `a` or `W`, consistently in Python and Worker search.
- Refresh channel cards in place after indexing/deletion, retain the current form settings, and support retrying a failed list refresh without reloading.
- Keep deletion validation and request errors inside the confirmation dialog, with accessible persistent feedback.
- Add shared short-title search contracts and setup regressions for success/failure, refreshed actions, list retries, and deletion errors.

- Make channel updates idempotent: preserve video timestamps and retained song/entry IDs, recover older discovered/filtered uploads, and retain progress on quota failure.
- Resolve handle URLs through the API directly; preserve quota errors and fix empty/undated historical backfill progress.
- Allow local-only channel deletion, revalidate names inside the delete transaction, and add independent site-sync retries with shared job exclusion.
- Use stable channel IDs in search links; reuse scoped Worker aggregates and lazily load expanded timelines with retry controls.
- Extract setup-page behavior into `static/setup.js`, guard against stale status responses, and export all local tables from one read snapshot.
- Add channel lifecycle, snapshot consistency, Worker query-count, and frontend interaction regressions.
- Fix capped incremental scans repeatedly spending their budget on filtered uploads; retain title-change and include-all rechecks.
- Defer patch foreign-key checks until atomic commit so artist promotion/demotion can move retained song and entry references; invalid final references still roll back.
- Preserve complete artist names and recognize bounded collaboration markers consistently in hosted search and entry filtering.
- Add shared artist fixtures, real Python-export-to-Worker integration coverage, and migration-backed Worker test databases.
- Extract indexing orchestration from the CLI and split Worker routing, HTTP helpers, search, and synchronization into modules.
- Bundle the Worker with a pinned esbuild dependency; verify generated code, assets, hosting configuration, and migrations against source.
- Add a cross-platform check command, align CI and contributor checks, and document functional contracts and architecture.

## [0.3.1] - 2026-09-17

- Keep portable build inputs under `packaging/` and generated executables under `build/portable/`.
- Add repository governance files and CI checks for generated output and local-data hygiene.

## [0.3.0] - 2026-09-17

- Add incremental site synchronization with automatic full-snapshot fallback.
- Add database-date-bounded channel updates and a per-channel incremental update action.
- Improve grouped search behavior and the local setup page.
- Publish a Windows portable package through the GitHub release.

## [0.2.2] - 2026-06-18

- Stabilize the hosted site release and local indexing workflow.
