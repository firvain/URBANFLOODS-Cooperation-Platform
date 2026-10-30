/**
 * The 22 seeded partner organisations (backend migration 0002), as `GET /organisations/` returns
 * them. `PARTNERS_RESPONSE` lists them shuffled so tests prove the view sorts by `sort_order`.
 */
import type { Organisation } from '@/services/organisations'

type Row = [number, 'PP' | 'AP', string, string, string, string | null]

const ROWS: Row[] = [
  [1, 'PP', 'UOWM', 'University of Western Macedonia', 'GR', 'https://www.uowm.gr/en/'],
  [2, 'PP', 'HEIS', 'Hydro-Engineering Institute Sarajevo', 'BA', 'http://heis.ba/'],
  [3, 'PP', 'DCMS', 'Development Centre Murska Sobota', 'SI', 'https://www.rcms.si'],
  [4, 'PP', 'MC', 'Macerata Municipality', 'IT', 'https://www.comune.macerata.it/'],
  [
    5,
    'PP',
    'RDA Backa',
    'Regional Development Agency Backa Ltd. Novi Sad',
    'RS',
    'https://www.rda-backa.rs',
  ],
  [
    6,
    'PP',
    'DEYAK',
    'Municipal Enterprise for Water Supply and Sewerage of Kozani',
    'GR',
    'https://www.deyakozanis.gr/',
  ],
  [7, 'PP', 'HydrowaterAL', 'Hydrowater-Albania', 'AL', 'https://hydrowateralbania.com/'],
  [8, 'PP', 'RDA Porin', 'Rijeka Development Agency PORIN Ltd.', 'HR', 'https://www.porin.hr'],
  [
    9,
    'PP',
    'FCSE-UKIM',
    'Ss. Cyril and Methodius University in Skopje (Faculty of Computer Science and Engineering)',
    'MK',
    'https://ukim.edu.mk',
  ],
  [
    10,
    'PP',
    'SVIMED',
    'SVI.MED. EuroMediterranean Center for the Sustainable Development',
    'IT',
    'https://www.svimed.eu',
  ],
  [11, 'PP', 'CKM', 'Center for Knowledge Management', 'MK', 'https://www.knowledge-center.org'],
  [12, 'AP', 'Scicli', 'Municipality of Scicli', 'IT', null],
  [13, 'AP', 'Modica', 'Municipality of Modica', 'IT', null],
  [14, 'AP', 'ARSO', 'Slovenian Environment Agency (ARSO)', 'SI', null],
  [15, 'AP', 'AVP Jadransko more', 'Agency for Watershed of the Adriatic Sea', 'BA', null],
  [16, 'AP', 'SHUKALB', 'Water Supply and Sewerage Association of Albania', 'AL', null],
  [
    17,
    'AP',
    'MEEN GDW',
    'Ministry of Environment and Energy, General Directorate for Water',
    'GR',
    null,
  ],
  [18, 'AP', 'Vode Vojvodine', 'Public Water Management Company "Vode Vojvodine"', 'RS', null],
  [19, 'AP', 'Kozani', 'Municipality of Kozani', 'GR', null],
  [20, 'AP', 'CMC', 'Center for Crisis Management', 'MK', null],
  [
    21,
    'AP',
    'TEMENUS',
    'Institute of Sustainable Development and Management of Natural Resources, UCRI TEMENUS, UOWM',
    'GR',
    null,
  ],
  [
    22,
    'AP',
    'Priroda',
    'Public Institution for Protected Area Management in the Primorje-Gorski Kotar County',
    'HR',
    null,
  ],
]

/** In `sort_order`. Ids differ from sort orders on purpose. */
export const PARTNERS: Organisation[] = ROWS.map(
  ([sort_order, type, short_name, name, country, website]) => ({
    id: 100 + sort_order,
    name,
    short_name,
    country,
    type,
    website,
    is_partner: true,
    sort_order,
    member_count: 0,
  }),
)

/** A deterministic shuffle (reverse, then swap pairs). */
const SHUFFLED = [...PARTNERS].reverse()
for (let i = 0; i + 1 < SHUFFLED.length; i += 2) {
  ;[SHUFFLED[i], SHUFFLED[i + 1]] = [SHUFFLED[i + 1]!, SHUFFLED[i]!]
}

export const PARTNERS_RESPONSE = { total: PARTNERS.length, items: SHUFFLED }
