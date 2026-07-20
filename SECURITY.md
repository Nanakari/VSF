# Security Policy

## Reporting a vulnerability

Do not disclose YouTube API keys, local databases, logs, or vulnerability details in a public issue.

Use GitHub Security Advisories for private reports when available. Otherwise, contact the repository owner through the GitHub profile and share only enough information to establish a private channel.

If an API key may have been exposed, revoke or restrict it in Google Cloud Console immediately and create a replacement when necessary.

## Local data

`.env`, SQLite databases, logs, and packaged executables are excluded from version control. Review diagnostic output and screenshots before sharing them because they may contain channel identifiers, local paths, or search history.
