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

The status doc lists three figures confirmed against primary sources.
Those are the ones used here:

| Figure | Value | Source |
|---|---|---|
| Mumbai, all 7 lakes, 30 Jun 2026 | **6.93%** | BMC Hydraulic Engineer's Dept. |
| Mumbai, all 7 lakes, 7 Aug 2026 | **88.50%** | mumbailakewaterlevel.in |
| Pune, all 5 dams, 7 Aug 2026 | **96.60%** | Maharashtra WRD / Pravah |

The Canva design used **8.34%**, **10.35%** and **90.06%** in places. Those
three, plus the 25 Jun statewide 53.38%, are **not** in the verified set.
They are still on the page but carry an `unverified` tag in the timeline, and
`script.js` logs a console warning listing how many remain. Either confirm
them against a source or cut them before the 11 Aug demo — the provenance
table lives at the top of `script.js` (`window.JALAAKAR_FIGURES` at runtime).

The swing headline reads **6.93% → 88.50%**, both verified, rather than the
mixed pair on the poster.

## Things left to wire up

- **Walkthrough video** — the Guide section renders a click-to-load YouTube
  facade (no iframe, no third-party cookies until clicked). Add the video id
  to `data-video-id` on `#video` in `index.html` to arm it.
- **Signup backend** — the form validates fully client-side and logs the
  payload it *would* POST to `/api/signup`. Nothing is persisted.
- **Live demo** — the dashboard in the laptop is a static CSS mockup with
  representative values, not live model output.
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
