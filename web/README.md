# Jalaakar — web frontend

Static frontend for **JALAAKAR / जलाकार**, built from the Canva design
(`DAHQ6pLflpQ`) in plain HTML, CSS and JavaScript. No build step, no
framework, no dependencies.

```
web/
├── index.html                 landing page
├── signup.html                account creation
├── styles.css                 all styling (numbered sections, see the header)
├── script.js                  all behaviour (numbered blocks)
├── assets/
│   ├── cracked-earth.svg      hero artwork — generated, see tools/
│   └── fonts/                 self-hosted Poppins + Noto Sans Devanagari
└── tools/
    └── gen_cracks.py          regenerates the hero artwork
```

## Running it

Open `index.html` directly, or serve the folder:

```bash
cd web && python3 -m http.server 8000   # → http://localhost:8000
```

A local server is preferable — opening over `file://` works but blocks
webfont loading in some browsers.

## Notes on the numbers

**The numbers on this page are no longer maintained here.** When the backend
is running, `script.js` fetches `GET /api/figures` and rewrites every element
carrying a `data-fig` attribute, along with its provenance tag. The API derives
those values from `ingest/reservoir_seeds.csv`, which is the same file the
ingest pipeline loads — so a correction to the data corrects the site, and the
two cannot drift.

The values in the markup are a **fallback** for when the API is unreachable
(useful on venue wifi). If they disagree with the API, the console prints the
mismatch and tells you to fix `index.html`.

Current set, after the 8 Aug re-sourcing:

| Figure | Value | Source | Status |
|---|---|---|---|
| Mumbai, 7 lakes, **29** Jun 2026 | **6.93%** | Free Press Journal / BMC Hydraulic Engineer | verified |
| Mumbai, 7 lakes, 30 Jun 2026 | **6.75%** | Mid-Day, citing BMC | verified |
| Mumbai, 7 lakes, 23 Jun 2026 | **8.34%** | Free Press Journal | verified |
| Mumbai, 7 lakes, 16 Jun 2026 | **10.35%** | RMSI climate blog | **unverified** |
| Mumbai, 7 lakes, 7 Aug 2026 | **88.50%** | mumbailakewaterlevel.in / BMC | verified |
| Pune, all 5 dams, 7 Aug 2026 | **96.60%** | Maharashtra WRD / Pravah | verified |

Two corrections worth knowing about, because both were on this page:

- **6.93% is 29 June, not 30 June.** FPJ's table is captioned *"Water Stock As
  On June 29"*; the article ran on the 30th. The 30 June reading is 6.75%.
- **53.38% (25 Jun, "statewide") has been deleted.** It cited the Jalaakar
  poster only, and BMC's own record contradicts it — 77.62% on 24 Jul and
  88.40% on 27 Jul. A 53% reading cannot sit between them. A tombstone comment
  in `script.js` records this so nobody re-adds it.

Only **10.35%** is still unverified. It carries the `unverified` tag, and
`script.js` logs a console warning while any remain.

The swing headline reads **6.93% → 88.50%**, both verified.

## Things left to wire up

- **Walkthrough video** — the Guide section renders a click-to-load YouTube
  facade (no iframe, no third-party cookies until clicked). Add the video id
  to `data-video-id` on `#video` in `index.html` to arm it.
- ~~**Signup backend**~~ — done. `POST /api/signup` in `api/` accepts exactly
  the payload `script.js` was already logging, applies the same phone
  validation, and resolves the free-text place to a real taluka, village or
  city aggregate. Run it with `uvicorn api.main:app --port 8000`, which also
  serves this folder.
  The form itself still submits client-side only — wiring the `fetch` call is
  the remaining step.
- **Live demo** — the dashboard in the laptop is a static CSS mockup with
  representative values, not live model output. `GET /api/score` now returns
  real cards; the mockup has not been wired to it yet.
  Note the mockup shows **Dindori, score 87, Critical**. Scored on real CGWB
  readings Dindori comes out **31/100, SAFE** — 137th of 164 talukas. **Baglan
  Taluka, also in Nashik, scores 78 / ACT NOW** and is the honest substitution.
- **Byline** — the footer credits Dheyay Shah, per the Canva design.

## Implementation notes

- **Hero artwork** is a generated Voronoi crack network, not a photo.
  `tools/gen_cracks.py` builds it (needs `numpy` + `scipy`); the seed is
  fixed so output is reproducible. Three layers — major fissures, secondary
  cracks, hairline crazing — plus `feTurbulence` grain and a vignette.
- **The laptop** is pure CSS. The dashboard inside uses container query units
  so type scales with the screen and the mockup stays proportional at any width.
- **Fonts are self-hosted** rather than pulled from Google Fonts, so the site
  renders identically with no network — worth having on venue wifi.
- **Progressive enhancement**: the animated counters ship their final values
  in the HTML and are only zeroed at the moment the animation starts, so the
  correct numbers show with JS disabled or if the observer never fires.
- **Reduced motion** is respected throughout — reveals and count-ups resolve
  instantly rather than animating.
- Responsive at 390 / 900 / 1080 / 1440. Nav collapses to a sheet under 900px.
