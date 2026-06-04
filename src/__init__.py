"""NAPA division 13077 data system.

Pipeline: fetch -> raw HTML archive -> parse -> SQLite -> views.
The app reads ONLY from the database; nothing user-facing touches the live site.
"""
