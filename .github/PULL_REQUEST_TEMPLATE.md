## Summary

<!-- Describe the user-visible change and why it is needed. -->

## Validation

- [ ] `python scripts/check.py` (Python and Worker checks)
- [ ] `npm run db:generate` leaves migrations unchanged, unless this PR changes the schema.
- [ ] Generated `dist/` output is rebuilt and included when Worker/site changes.

## Checklist

- [ ] No `.env`, API key, SQLite database, log, screenshot, or packaged executable is included.
- [ ] Database/schema or re-indexing impact is documented when applicable.
- [ ] README or changelog is updated when behavior changes.
- [ ] Search or synchronization contract changes include shared fixtures or integration coverage.
