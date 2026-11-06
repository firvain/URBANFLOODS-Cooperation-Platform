# FAIR data

This document explains how the Cooperation Platform meets the FAIR principles (Findable,
Accessible, Interoperable, Reusable) committed to in the URBANFLOODS application form: which
identifiers, formats, metadata and licence it uses, where the open data can be fetched, and what
is deliberately left out to protect personal data. The public-facing version for reusers is the
`/open-data` page drafted in [legal/open-data.md](legal/open-data.md); the endpoints are listed
in [api.md](api.md#open-data-exports-feeds-sitemap).

Last updated: 2026-10-31

## 1. Scope

Open data = everything **published** on the platform: blog posts with their published comments,
forum threads with their published replies, and their metadata (title, language, category, tags,
dates, KNOWBASE links, canonical URL, author display name and organisation). Pending, hidden and
deleted content, reports, moderation data and account data are not open.

## 2. Findable

| Measure | Implementation |
|---|---|
| Persistent identifiers | every post, thread, reply and comment has a numeric id that is never reused (soft delete keeps the row) |
| Stable URLs | `https://cooperation.urbanfloods.app/blog/<slug>` and `/forum/t/<slug>`; the slug is set at creation and not changed by title edits (only an admin can change it explicitly); given as `url` in the exports |
| Feed identifiers | Atom entries carry `tag:` URIs (RFC 4151), e.g. `tag:cooperation.urbanfloods.app,2026:post:42` (`backend/app/api/v1/endpoints/feeds.py`) |
| Sitemap | `/sitemap.xml` lists the static pages and every published post and thread with `lastmod`; `/robots.txt` points to it |
| Rich metadata | categories, free tags, content language (`locale`), publication and update dates, KNOWBASE links |
| Embedded metadata | schema.org JSON-LD in the page head: `WebSite` with `SearchAction` (home), `Article` (posts), `DiscussionForumPosting` (threads) (`frontend/src/composables/usePageHead.ts`) |
| Data set description | `/api/v1/export/datapackage.json`: name, title, description, keywords, homepage, created, sources, contributors, licences, resources |
| Search | `GET /api/v1/search/` full-text over titles and bodies; list filters by category, tag, author, locale |
| DOI | not minted by the platform; a yearly snapshot of the exports could be deposited on Zenodo. [CHECK: decision by the partnership] |

## 3. Accessible

- All published content is readable without an account, over HTTPS, with plain HTTP `GET`.
- The bulk exports, feeds and sitemap need no key and no cookie.
- The API is documented in OpenAPI 3 at `/api/v1/openapi.json`, with interactive docs at `/docs`
  (when `ENABLE_DOCS=true`; see [api.md](api.md#1-basics)).
- Exports send `ETag` and `Last-Modified`; a matching `If-None-Match` gets 304 (weak comparison), so
  harvesters can poll cheaply. The ETag changes with anything the export shows: the content, its
  authors' names or erasure, organisations, categories, tags and KNOWBASE links.
- Fair-use limit: 300 requests per minute per IP under `/api/` (429 with `Retry-After` beyond);
  feeds and the sitemap are not rate limited by the application.
- Metadata outlives content: a deleted account's contributions stay, attributed to "Deleted user".

## 4. Interoperable

| Format | Where | Standard |
|---|---|---|
| JSON | `/api/v1/export/posts.json`, `/api/v1/export/threads.json`, all API responses | RFC 8259; timestamps ISO 8601 in UTC |
| CSV | `/api/v1/export/posts.csv` | RFC 4180, UTF-8, header row; formula-like cells prefixed with `'` |
| Data package | `/api/v1/export/datapackage.json` | Frictionless Data Package v2 with a Table Schema for the CSV |
| Atom | `/feeds/posts.atom`, `/feeds/threads.atom` | Atom 1.0 (RFC 4287), 20 newest items |
| Sitemap | `/sitemap.xml` | sitemaps.org 0.9 |
| JSON-LD | page head | schema.org |

Shared vocabularies: ISO 3166-1 alpha-2 country codes for organisations; language codes for
`locale`; KNOWBASE identifiers (`kb_type` = `document` or `measure`, `kb_id`) so contributions can be
joined to the KNOWBASE's own data. The 3rd project meeting listed an XML export; the XML formats
provided are Atom and the sitemap, there is no XML version of the bulk exports. [CHECK]

## 5. Reusable

- **Licence**: CC BY 4.0 (`CONTENT_LICENSE_URL`), stated in the Terms of Use, in the data package
  (`licenses`, at package and resource level) and on every exported post and thread
  (`license: "CC-BY-4.0"`, `license_url`).
- **Provenance**: author display name, author organisation (id, name, short name, country),
  `published_at`, `updated_at`, canonical `url`; the data package names the project
  (IPA-ADRION00374, Interreg IPA ADRION) and the platform as sources and the partnership as
  publisher.
- **Documentation**: this file, [api.md](api.md), the Table Schema in the data package, and the
  public `/open-data` page.
- **Clean content**: bodies are exported as sanitised HTML and as plain text.

## 6. Metadata fields

Exported post (`/export/posts.json`); threads have the same fields without `excerpt`, `event_at`,
`event_url` and with `replies` instead of `comments` (`backend/app/api/v1/schemas/export.py`).

| Field | Content |
|---|---|
| `id`, `slug`, `url` | identifier, slug, canonical page URL |
| `title`, `excerpt` | title; summary (posts) |
| `locale` | language of the item |
| `category` | `{slug, name}` |
| `tags` | list of `{slug, name}` |
| `author` | `{id, display_name, organisation: {id, name, short_name, country} or null}`; `id` null and "Deleted user" for erased accounts |
| `published_at`, `updated_at` | UTC timestamps |
| `body_text`, `body_html` | plain text and sanitised HTML |
| `event_at`, `event_url` | optional event date and link (posts) |
| `knowbase_links` | list of `{kb_type, kb_id, title}` |
| `comments` / `replies` | `{id, author, body_text, created_at}` (replies also `parent_reply_id`) |
| `license`, `license_url` | `CC-BY-4.0` and the licence URL |

CSV columns: `id`, `slug`, `title`, `locale`, `category`, `tags` (`;`-separated), `author`,
`organisation`, `published_at`, `url` (no bodies).

## 7. Limits and personal data minimisation

- Exports, feeds and the sitemap never contain email addresses, country, biography, expertise,
  account settings, sessions, IP addresses or the audit log. The author is identified only by
  display name, a numeric id and the chosen organisation.
- Uploaded images are referenced by URL inside `body_html`, not bundled.
- KNOWBASE content is not copied into the exports, only the linked item ids and titles; the
  KNOWBASE has its own interface; its content is also CC BY 4.0 (partnership decision, recorded
  2026-11-06; official legal texts and quoted third-party material excluded).
- Only published content is exported. Content removed by moderation disappears from the next
  export; copies already harvested elsewhere cannot be recalled.
- The members directory (`GET /api/v1/members/`, public) shows, for verified members who did not
  opt out (`show_in_directory`, on by default), display name, organisation, country, bio excerpt
  and expertise, and the email address only if the member opted in (`show_email`). It is part of
  the networking feature, not of the open-data exports. [CHECK: confirm the default with the
  privacy policy]
- The exports are generated live from the database; there is no versioned archive unless a
  snapshot is deposited (see DOI above).
