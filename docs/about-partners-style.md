# About and Partners pages: style and facts

User requirement (2026-10-30): the Partners page must look like
https://knowbase.urbanfloods.app/about and reuse that page's UI style where it fits. Source of
the style: `/Users/firvain/URBANFLOODS-Knowbase/frontend/src/views/AboutView.vue` (read-only
reference). Light mode only here, so drop every `dark:` class when copying.

## Style vocabulary (from the KNOWBASE About page)

- Container: `UContainer` with `pt-8 pb-4 lg:pb-24`, content in `max-w-4xl mx-auto`.
- Page header: `h1` `text-4xl font-bold mb-4 text-primary-600`, followed by a short accent bar
  `<div class="h-1 w-20 bg-secondary-500 rounded">`.
- Main surface: one `UCard` with `space-y-6`, the project logo centred at the top
  (`flex justify-center mb-8`, `max-w-full h-auto`).
- Section headings: `h2` `text-2xl font-bold text-secondary-600`; subsection `h3`
  `text-lg font-semibold text-secondary-600`; field labels `h3`
  `text-sm font-semibold text-gray-500 uppercase mb-2`; values `text-base` / `text-xl font-bold`.
- Highlight box: `p-4 bg-primary-50 rounded-lg border-l-4 border-primary-500`.
- Lead partner card: `p-4 bg-primary-100 rounded-lg border-2 border-primary-500` with a
  `UBadge color="primary" variant="solid" size="xs"` reading **LEAD**, bold name in
  `text-primary-700`, address, and a contact block separated by `border-t border-primary-200`.
- Partner tiles: `grid grid-cols-1 md:grid-cols-2 gap-2`, each tile
  `p-3 bg-secondary-50 rounded border border-secondary-200`, name in `text-sm font-medium`.
- Grids of facts: `grid grid-cols-1 md:grid-cols-2 gap-6` (and `md:grid-cols-3`).
- Body copy: `text-gray-600 space-y-4 text-sm leading-relaxed`.
- Priority icon: `INTERREG-icons-B1.png` (`h-12 w-12`) beside the priority text. Copy the icon
  from the KNOWBASE repo into `src/assets/logos/priority-2-greener.png`.

## Facts for the About page (from the KNOWBASE About page; authoritative project data)

| Field | Value |
|---|---|
| Acronym | URBANFLOODS |
| Full title | Promoting Urban Resilience Through an Integrated Advanced Decision Support System for Flood Control |
| Programme | Interreg IPA ADRION 2021–2027 |
| Call | IPA ADRION 1st Call for Proposals |
| Priority | 2. Supporting a greener and climate resilient Adriatic-Ionian region |
| Specific objective | SO2.1. Promoting climate change adaptation and disaster risk prevention, resilience taking into account eco-system based approaches |
| Start – end | 01/09/2024 – 31/08/2027 |
| Total budget | EUR 1.747.583,17 |
| Interreg funds | EUR 1.485.445,68 |
| Lead partner | University of Western Macedonia, Active Urban Planning Zone (ZEP) I, 50100 Kozani, Greece |
| Scientific coordinator | Prof. Malamati Louta, louta@uowm.gr |

These replace the "budget figures to be provided" placeholder. The project summary text on the
KNOWBASE About page may be reused verbatim (same project, same lead partner).

## Partners page (`/partners`, increment 1k)

- Same header pattern (h1 + accent bar), then one `UCard`.
- **Lead partner** card as above (UOWM), with website link.
- **Project partners** (10) as the tile grid, each tile: name, country (flag from `flag-icons`
  imported locally in this component only, plus the country name via `Intl.DisplayNames`),
  short name badge, website link (external, new tab).
- **Associated partners** (11) in a second tile grid with the same tile, under its own `h3`.
- Data comes from `GET /api/v1/organisations/` (increment 1h), partners first (`is_partner`),
  LP/PP before AP, by `sort_order`. The LP is the row with `short_name == 'UOWM'`
  (type `PP`, sort_order 1).
- Logos: the project logo only (centred at the top of the card). No partner logos yet; if they are
  added later, none may exceed the EU emblem height on the page (docs/branding.md).
- Counts line under the h1: "11 project partners and 11 associated partners from 8 countries".
