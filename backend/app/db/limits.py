"""Id ranges of the database columns (7n), shared by the API's bounded id types
(``app/api/v1/params.py``) and the crud code that must not ask Postgres for an id past them."""

# Posts, threads, users, categories, tags, organisations, expertise tags, uploads, KNOWBASE ids.
MAX_ID = 2**31 - 1
# Replies, comments, reports, audit log.
MAX_BIGINT_ID = 2**63 - 1
