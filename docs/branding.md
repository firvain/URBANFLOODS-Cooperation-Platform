# Branding and visibility rules for the platform

Source: "IPA ADRION 2021-27 Project Brand & Visibility Guidelines" (`docs/IPA ADRION project Brand
& Visibility Guidelines.pdf`), the project website https://urbanfloods.interreg-ipa-adrion.eu and
the sibling KNOWBASE app. Non-compliance can have financial consequences for the project
(guidelines §2.9), so these rules are treated as requirements.

## The project logo (guidelines §1.1–1.10)

- The project logo is one invariable unit: Interreg logotype + EU emblem + "Co-funded by the
  European Union" + "IPA ADRION" + the acronym **URBANFLOODS** (Montserrat Regular, Priority 2 green
  `#9ACA3C`). Elements are never shown separately, recoloured, cropped, rotated, outlined,
  stretched or reordered. The acronym is never typeset by us; the logo is always the supplied image.
- Two official layouts: **stacked** (acronym under a thin line) and **horizontal** (acronym to the
  right of a vertical line) for small spaces. Files in `frontend/src/assets/logos/`:
  - `interreg-urbanfloods-stacked.png` (from the project website) — About page, Partners page, emails.
  - `interreg-urbanfloods-horizontal.png` (as used by KNOWBASE) — header (every page).
  - `urbanfloods-wordmark.svg` — the project's own illustrated logo (city and floods with
    "Urban FLOODS"). Used in the **footer** (user decision 2026-10-30) and as a decorative element.
    It never replaces the official lock-up where that is required; the header lock-up on every
    page satisfies the visibility rule, and the co-funding statement stays in the footer.
- **Ideal use: on a white background.** On a coloured background or photo it must sit inside a
  white rectangle. (This is one reason the app is light mode only.)
- **Minimum width on screen**: 300 px on laptop/desktop, 240 px on tablet/smartphone, measured on
  the Interreg logotype + EU emblem part (not the statement). Practical interpretation adopted on
  2026-10-30 (same as the KNOWBASE app):
  - Footer and About page: the **stacked** logo rendered at 560 px (lg) / 448 px (below lg) image
    width, which gives ≥ 300 / ≥ 240 px on the measured part. Literal compliance.
  - Header: the **horizontal** logo at 300 px (lg) / 240 px (below lg) image width. Measured
    literally this is ≈ 94 / 75 px, because the measured part is only ~31 % of the horizontal
    image; a literally compliant header logo would be ~960 px wide, which no header can carry.
    The full logo is nonetheless on every page at compliant size in the footer. Confirm with the
    JS (Joint Secretariat) if in doubt (guidelines §1.10 invites this).
- **Clear space**: at least half the EU emblem height on every side; nothing else inside it.
- **Other logos on the same page** (partner logos on `/partners`, `/about`): none may be taller than
  the EU flag emblem inside the project logo on that page. Render partner logos in a uniform row
  with a max height equal to the emblem height of the page's project logo, and keep the project
  logo on the same page.
- Favicon and app icons: the project favicon set (from the project website / KNOWBASE) in
  `frontend/public/` with a `site.webmanifest`; `theme_color` white.

## Colours

- Programme colours: Reflex Blue `#0d428d`, light blue `#9fade7`, yellow `#fbec4b`.
- Priority 2 ("greener and climate resilient", URBANFLOODS' priority): green `#9ACA3C`.
- The UI palette stays the KNOWBASE one for sibling consistency: primary `#11395c`, secondary
  `#97c137` (used for backgrounds and accents only, not body text, for contrast). These are the
  Nuxt UI `primary` / `secondary` colours already configured.
- **Light mode only.** No dark mode, no system-preference switching. Nuxt UI colour mode is forced
  to light and the toggle is not offered.

## Typography

- Logo acronym font is Montserrat Regular, embedded in the logo image. UI font stays Noto Sans
  (system stack, not loaded from Google Fonts, to avoid third-party requests).

## Mandatory texts (guidelines §2.2–2.4)

- **Statement on the Interreg support**, visible on every page (footer):
  "The project is co-funded by the European Union through the Interreg IPA ADRION programme."
  (i18n key `footer.statement`; translated in all locales.)
- **Disclaimer**, at the bottom of the site (footer, smaller text):
  "This website has been produced with the financial assistance of the European Union. The content
  of the website is the sole responsibility of the University of Western Macedonia and can under no
  circumstances be regarded as reflecting the position of the European Union and/or IPA ADRION
  programme authorities." (i18n key `footer.disclaimer`.)
- Footer links: programme website https://www.interreg-ipa-adrion.eu, project website
  https://urbanfloods.interreg-ipa-adrion.eu, project LinkedIn page
  https://www.linkedin.com/company/urbanfloods/, KNOWBASE https://knowbase.urbanfloods.app.
- **About page** (§2.2 content for a project web presence): short description with aims and results,
  the project logo, the EU financial support received (budget figures to be supplied by the LP),
  link to the project website, project duration, partners.

## Checklist for every view

- Project logo visible (header), not narrower than the minimum, on white, with clear space.
- Footer carries the statement and the disclaimer.
- No other logo taller than the EU emblem on the same page.
- Light background behind any logo.
