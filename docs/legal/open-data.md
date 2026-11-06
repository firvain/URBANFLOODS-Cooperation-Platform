# Open Data — URBANFLOODS Cooperation Platform

**Version 1.1 (draft for review), 6 November 2026.** This is the text the platform's `/open-data`
page will show (increment 5e). It describes the FAIR (findable, accessible, interoperable,
reusable) data offer of https://cooperation.urbanfloods.app. Items marked **[CHECK]** need
confirmation before go-live.

---

## 1. What is open

Everything published on the Platform can be read by anyone, without an account, and reused under
an open licence. The open data comprises:

- published **blog posts**, with their published **comments**;
- published **forum threads** (discussions), with their published **replies**;
- their metadata: title, language, category, tags, publication and update dates, links to
  KNOWBASE items, and the canonical page address;
- for each contribution, the author's **display name** and, if the author chose one, their
  **organisation** (name, short name and country).

## 2. Licence and attribution

Contributions are © their authors and licensed under the **Creative Commons Attribution 4.0
International licence (CC BY 4.0)**, https://creativecommons.org/licenses/by/4.0/ (Terms of Use,
section 8). You may share and adapt the data for any purpose, including commercially, provided you
give appropriate credit, link to the licence and indicate if changes were made.

When you reuse the data set as a whole, credit it as:

> URBANFLOODS Cooperation Platform contributors, CC BY 4.0, https://cooperation.urbanfloods.app

When you reuse a single contribution, also name its author (the display name shown on the page and
in the export) and link to the contribution's page.

## 3. How to get the data

All addresses below are public and need no account or key.

### 3.1 Bulk exports

| Resource | Address | Format |
|---|---|---|
| Blog posts, with comments and KNOWBASE links | https://cooperation.urbanfloods.app/api/v1/export/posts.json | JSON array |
| Forum threads, with replies and KNOWBASE links | https://cooperation.urbanfloods.app/api/v1/export/threads.json | JSON array |
| Blog posts, one row per post, without bodies | https://cooperation.urbanfloods.app/api/v1/export/posts.csv | CSV (UTF-8, comma-separated, with header) |
| Data package descriptor | https://cooperation.urbanfloods.app/api/v1/export/datapackage.json | Frictionless Data Package (v2) |

The **data package descriptor** lists the three exports with their licence, sources, contributors
and, for the CSV file, a table schema describing every column. Tools that understand Frictionless
Data (for example the `frictionless` Python and R libraries) can load and validate the whole set
from that single address.

Each post and thread in the JSON exports carries its body as plain text and as cleaned HTML, its
licence (`CC-BY-4.0`) and the licence address. In the CSV file, text cells that begin with `=`,
`+`, `-` or `@` are prefixed with an apostrophe so spreadsheet applications do not run them as
formulas.

The exports are generated on request from the live database, so they are always current. They
support HTTP caching: send the `ETag` you received in an `If-None-Match` header and you get a short
"304 Not Modified" answer when nothing has changed.

### 3.2 Feeds

Atom 1.0 feeds of the 20 newest published items, for feed readers and automated monitoring:

- blog: https://cooperation.urbanfloods.app/feeds/posts.atom
- forum: https://cooperation.urbanfloods.app/feeds/threads.atom

### 3.3 Sitemap

https://cooperation.urbanfloods.app/sitemap.xml lists the public pages and every published post
and thread with its last modification date, for search engines and harvesters.

### 3.4 API

The Platform's REST API is described in OpenAPI format at
https://cooperation.urbanfloods.app/api/v1/openapi.json. Its public read endpoints (posts,
threads, categories, tags, search) return the same published content as the exports.

### 3.5 Fair use

To keep the service available for everyone, requests to the API and the exports are limited to
**300 per minute** from one network address; beyond that you receive an HTTP 429 answer with a
`Retry-After` header. The bulk exports return everything in one request, so there is no need to
crawl the pages. Please identify your application in the `User-Agent` header when harvesting
regularly. **[CHECK: limits after the production deployment]**

## 4. What is not open

The following data is never included in the exports, feeds or API answers:

- **personal data** beyond the display name and the organisation, for example email addresses,
  country, biography or expertise areas of members, account settings, sessions and the audit log;
- content that is **not published**: pending, hidden or deleted posts, threads, replies and
  comments;
- reports, moderation decisions and other administrative data.

Contributions of members who have deleted their account remain available, attributed to
"Deleted user" (Privacy Policy, section 7).

**Images** uploaded by members are covered by the same CC BY 4.0 licence. They are referenced by
their address inside the HTML bodies of the JSON exports but are not bundled as files.

## 5. The URBANFLOODS KNOWBASE

The URBANFLOODS KNOWBASE (https://knowbase.urbanfloods.app), with flood-management measures,
policies and legislation from the Adriatic-Ionian region, is a separate open resource with its own
interface. Its content is licensed by the URBANFLOODS partnership under the same **CC BY 4.0**
licence. Credit it as:

> URBANFLOODS KNOWBASE, URBANFLOODS project (IPA-ADRION00374), Interreg IPA ADRION. CC BY 4.0.
> https://knowbase.urbanfloods.app

The licence does not cover official legal texts themselves, which are available from their
official sources, or third-party material quoted in the KNOWBASE, which keeps its own rights.

The Platform's exports contain only the identifiers and titles of the KNOWBASE items linked from a
contribution, not the KNOWBASE content itself.

## 6. Persistent identifiers

- Every post, thread, reply and comment has a **stable numeric identifier** that is never reused.
- Every post and thread has a **page address** built from its slug, for example
  `https://cooperation.urbanfloods.app/blog/<slug>` and
  `https://cooperation.urbanfloods.app/forum/t/<slug>`; the same address is given as `url` in the
  exports. The slug is set when the item is created and does not change when its title is edited,
  but it can be corrected exceptionally; for a permanent reference, use the numeric identifier or
  the `tag:` URI.
- Feed entries carry permanent `tag:` URIs (RFC 4151), such as
  `tag:cooperation.urbanfloods.app,2026:post:42`, which do not change when a title is edited.

**[CHECK: whether a DOI should be minted for a yearly snapshot of the data set, e.g. on Zenodo]**

## 7. How to cite

> URBANFLOODS Cooperation Platform contributors (2026). *URBANFLOODS Cooperation Platform: blog
> posts and forum threads* [data set]. University of Western Macedonia, URBANFLOODS
> (IPA-ADRION00374), Interreg IPA ADRION. CC BY 4.0.
> https://cooperation.urbanfloods.app/api/v1/export/datapackage.json (accessed on: date).

## 8. Contact

For questions about the open data, reuse or errors in the data set, contact Prof. Malamati Louta,
Scientific Coordinator of URBANFLOODS, University of Western Macedonia, louta@uowm.gr.

## 9. Funding statement

The project is co-funded by the European Union through the Interreg IPA ADRION programme. This
Platform has been produced with the financial assistance of the European Union. Its content is the
sole responsibility of the University of Western Macedonia and can under no circumstances be
regarded as reflecting the position of the European Union and/or the IPA ADRION programme
authorities.

---

## Notes for the reviewer (not part of the page)

- Every address and behaviour stated here is implemented as of 31 Oct 2026:
  `backend/app/api/v1/endpoints/export.py` (posts.json, threads.json, posts.csv,
  datapackage.json; ETag/If-None-Match; CSV formula guard), `feeds.py` (Atom feeds of 20 items,
  `tag:` ids with year 2026, sitemap, robots.txt), `schemas/export.py` (author = id, display name,
  organisation; never email; deleted authors as "Deleted user"), `core/rate_limit.py` (300 requests
  per minute per IP on /api/ paths; feeds and sitemap are not rate limited by the app).
- The OpenAPI description depends on `ENABLE_DOCS=true` in production (docs/PLAN.md keeps it on as
  part of the FAIR offer). Make sure `.env.prod` sets it in M6.
- Slugs: set at creation from the title; `crud/post.py` allows an explicit slug change on update,
  hence the wording in section 6.
- The CSV formula guard also covers tab and carriage return; the page names only the visible
  characters.
- Version 1.1 (6 Nov 2026): KNOWBASE licence CC BY 4.0, agreed by the partnership, with the
  exclusions for official legal texts and third-party material (section 5).
- Open items: production rate limits; DOI snapshot; Greek-language version.
