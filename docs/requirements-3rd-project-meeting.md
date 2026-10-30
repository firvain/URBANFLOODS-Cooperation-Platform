# Requirements presented at the 3rd Project Meeting (A5.1, 20–21 January 2026)

Source: "LP_A5.1 Cooperation Platform", UOWM presentation, 3rd Project Meeting, Murska Sobota.
These were shown to all partners and therefore set expectations for D.5.1.1 beyond the
application form text. This file records them and maps each to the plan.

## Summary table of technical requirements (slide 3)

| Goal | Technical implementation | Plan status |
|---|---|---|
| Sync with KNOWBASE **and DSS** | RESTful APIs | KNOWBASE: proxy in M2. **DSS: not in plan yet** (see open points) |
| "Blog-style" interactivity | Responsive web framework | M2/M3 (Vue 3 + Nuxt UI) |
| Accessibility for disabled users | **WCAG 2.1 compliance** | M5 a11y pass + axe; target is WCAG 2.1 AA, stated explicitly |
| Discoverability and reuse | Metadata tagging / open formats (FAIR) | M5 export; JSON-LD promoted to core (was extended) |
| Durability after project end | Documentation and Dockerization | M0 Docker, M5 docs, M6 deploy |

## Architectural design (slide 4) → plan mapping

| Block in the slide | Plan |
|---|---|
| Web browser / mobile app; WCAG 2.1 responsive UI; semantic HTML and ARIA landmarks | Responsive SPA; mobile covered by responsive design, no native app |
| Unified IAM and RBAC: secure login (SSL/OAuth), roles PPs / stakeholders / public | Session login over HTTPS; roles member / admin / superadmin; organisation ties users to PPs. OAuth not planned (optional later) |
| Application server and CMS (blog engine): content management, threading and commenting, tagging and search | M2 posts + tags, M3 threads/replies/comments, M5 search |
| API integration layer (connectors and sync) → KNOWBASE and Unified DSS | KNOWBASE proxy (M2). **DSS connector: open point** |
| Profile database (PostgreSQL): user expertise and matchmaking | Profiles exist (1a). **Expertise tags + matchmaking: open point** |
| Interoperability and FAIR: standardized metadata (JSON-LD), open file export (CSV, XML), permanent identifiers (DOIs) | JSON-LD on public pages (core); CSV/JSON export (5b); XML export added to 5b; DOI via Zenodo deposit of the final export at project end (process, not code) |
| Sustainability: modular codebase (git), containerization (Docker), automated backups, monitoring tools (RCO87 tracking) | Git/Docker done; backups in M6; RCO87 = organisations cooperating → admin stats export (4d) must report it explicitly |

## Conceptual UI (slide 5) → plan mapping

| UI element | Plan |
|---|---|
| Nav: Home · KNOWBASE Library · Unified DSS Tool · Collaboration Network · Policy Toolkit · Log in / Register | Routes: `/`, `/knowbase`, **`/dss` (open point)**, `/network` (partners + members), `/toolkit` (filtered KNOWBASE measures/policies), `/login`, `/register`. Blog = "Latest insights and best practices"; forum lives under Collaboration Network |
| Search "best practices, partners, or data" | Header search (5c) over posts/threads, extended to members/organisations and KNOWBASE |
| Partner matchmaking: suggested collaborators by expertise, "Connect" | **Open point** |
| Access Unified DSS (map view) | **Open point** |
| Recent activity feed | Home page widget from posts/threads/replies (M3) |
| Posts with tags, Read more, Download PDF, Comments | Posts (M2), comments (M3); "Download PDF" = print stylesheet / browser PDF (extended) |
| KNOWBASE highlights: featured resource (Succinct List of Measures download) | Admin-only "Resources" category with link cards (2g) + home widget |
| Policy Toolkit filter: region, timeline short/mid/long-term | Region = country filter via KNOWBASE API. Timeline facet depends on WP3 adding it to KNOWBASE; until then a platform-side tag on Resources posts |
| Upcoming events / webinars | Blog category "Events" with an optional event date on posts (small schema addition in 2a) |
| Footer: About, Contact, Accessibility Statement, FAIR Data Principles, partner logos, accessibility widget | Static pages (5e); partner logos row; no third-party accessibility overlay (built-in a11y instead) |

## Open points for the user (decisions that change the build)

1. **Unified DSS integration.** The slide promises REST sync and a map view. Is there a DSS API or URL today? Minimum viable: a "Unified DSS" nav link to the DSS web app plus an embedded status card. Full: proxy DSS endpoints like KNOWBASE.
2. **Partner matchmaking.** Expertise tags on profiles, a members directory under Collaboration Network filterable by expertise/country/organisation, and "suggested collaborators" on the home page. Contact via opt-in email reveal or an internal message? Needs consent handling (GDPR).
3. **Events / webinars.** Add `event_at` (and optional `event_url`) to posts so the Events category can show upcoming items in date order.
