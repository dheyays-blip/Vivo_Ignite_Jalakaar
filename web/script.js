/* ==========================================================================
   JALAAKAR — frontend behaviour
   Plain ES2015+, no dependencies. Safe to load on both index.html and
   signup.html; every block bails out early if its markup isn't present.
   ========================================================================== */
(function () {
  'use strict';

  /* ----------------------------------------------------------------------
     FIGURE PROVENANCE
     The HTML is the single source of truth for what renders. This table
     exists so the numbers on the page can be traced to a source, and so a
     mismatch is caught in the console instead of on stage.

     Verified = independently confirmed against the primary source.
     Unverified figures are tagged in the markup and MUST be either
     confirmed or cut before the 11 Aug demo.
     -------------------------------------------------------------------- */
  var FIGURES = {
    mumbai7Lakes_29Jun2026: { value: 6.93,  unit: '%', verified: true,
      source: 'Free Press Journal / BMC Hydraulic Engineer' },
    mumbai7Lakes_30Jun2026: { value: 6.75,  unit: '%', verified: true,
      source: 'Mid-Day, citing BMC data' },
    mumbai7Lakes_07Aug2026: { value: 88.50, unit: '%', verified: true,
      source: 'mumbailakewaterlevel.in' },
    pune5Dams_07Aug2026:    { value: 96.60, unit: '%', verified: true,
      source: 'Maharashtra WRD / Pravah' },

    mumbai_16Jun2026:       { value: 10.35, unit: '%', verified: false, source: null },
    mumbai_23Jun2026:       { value: 8.34,  unit: '%', verified: true,
      source: 'Free Press Journal / BMC Hydraulic Engineer' },

    /* RETRACTED 8 Aug 2026 — kept as a tombstone so nobody re-adds it.
       statewide_25Jun2026 = 53.38% cited the Jalaakar poster only, and BMC's
       own record contradicts it: 77.62% on 24 Jul, 88.40% on 27 Jul. A 53%
       reading cannot sit between them.
       mumbai7Lakes_30Jun2026 was 6.93%. Right number, wrong date — FPJ's table
       is captioned "Water Stock As On June 29". 30 Jun is 6.75%. */

    warningWindowDays:      { value: 30,    unit: 'days',  verified: true, source: 'product spec' },
    tankerCostPune:         { value: 3000,  unit: 'INR',   verified: false, source: null },
    cgwbOverExploited:      { value: 730,   unit: 'units', verified: false, source: 'CGWB' },
    wellsDecliningPct:      { value: 33,    unit: '%',     verified: false, source: 'CGWB' },
    deployedSystemCost:     { value: 0,     unit: 'INR',   verified: true, source: 'open data only' },
    validationRigCost:      { value: 2645,  unit: 'INR',   verified: true, source: 'bill of materials' }
  };

  // Expose for console inspection during the demo / debugging.
  window.JALAAKAR_FIGURES = FIGURES;

  var prefersReduced = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var $  = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  };

  /* ------------------------------------------------------------------ */
  /* 1. Sticky nav shadow                                                */
  /* ------------------------------------------------------------------ */
  (function stickyNav() {
    var nav = $('#nav');
    if (!nav) return;

    var ticking = false;
    function update() {
      nav.classList.toggle('is-stuck', window.scrollY > 24);
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
    update();
  })();

  /* ------------------------------------------------------------------ */
  /* 2. Mobile menu                                                      */
  /* ------------------------------------------------------------------ */
  (function mobileMenu() {
    var toggle = $('#navToggle');
    var links  = $('#navLinks');
    if (!toggle || !links) return;

    function setOpen(open) {
      links.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    }

    toggle.addEventListener('click', function () {
      setOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });

    links.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') setOpen(false);
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') setOpen(false);
    });

    window.addEventListener('resize', function () {
      if (window.innerWidth > 900) setOpen(false);
    });
  })();

  /* ------------------------------------------------------------------ */
  /* 3. Reveal on scroll                                                 */
  /* ------------------------------------------------------------------ */
  (function reveal() {
    var items = $$('[reveal]').concat(
      $$('[reveal-group]').reduce(function (acc, g) {
        return acc.concat(Array.prototype.slice.call(g.children));
      }, [])
    );
    if (!items.length) return;

    if (prefersReduced || !('IntersectionObserver' in window)) {
      items.forEach(function (el) { el.classList.add('is-in'); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -12% 0px', threshold: 0.12 });

    items.forEach(function (el) { io.observe(el); });
  })();

  /* ------------------------------------------------------------------ */
  /* 4. Count-up numbers                                                 */
  /* ------------------------------------------------------------------ */
  (function counters() {
    var els = $$('.count');
    if (!els.length) return;

    function render(el, v, decimals) {
      el.textContent = decimals
        ? v.toFixed(decimals)
        : Math.round(v).toLocaleString('en-IN');
    }

    function run(el) {
      var target   = parseFloat(el.getAttribute('data-count-to')) || 0;
      var decimals = parseInt(el.getAttribute('data-decimals'), 10) || 0;

      // The final value is already in the HTML (so it is correct with JS off
      // or the observer never firing). Only zero it out at the moment we
      // actually start animating.
      if (prefersReduced) { render(el, target, decimals); return; }
      render(el, 0, decimals);

      var duration = 1500;
      var start    = null;

      function step(ts) {
        if (start === null) start = ts;
        var p = Math.min((ts - start) / duration, 1);
        // easeOutExpo — fast out of the gate, settles gently on the number
        var eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
        render(el, target * eased, decimals);
        if (p < 1) window.requestAnimationFrame(step);
      }
      window.requestAnimationFrame(step);
    }

    if (!('IntersectionObserver' in window)) { els.forEach(run); return; }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        run(entry.target);
        io.unobserve(entry.target);
      });
    }, { threshold: 0.5 });

    els.forEach(function (el) { io.observe(el); });
  })();

  /* ------------------------------------------------------------------ */
  /* 5. Scroll-spy for nav links                                         */
  /* ------------------------------------------------------------------ */
  (function scrollSpy() {
    var links = $$('.nav__links > a[href^="#"]');
    if (!links.length || !('IntersectionObserver' in window)) return;

    var map = {};
    var sections = links.map(function (a) {
      var id = a.getAttribute('href').slice(1);
      var el = document.getElementById(id);
      if (el) map[id] = a;
      return el;
    }).filter(Boolean);
    if (!sections.length) return;

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        links.forEach(function (a) { a.classList.remove('is-active'); });
        var active = map[entry.target.id];
        if (active) active.classList.add('is-active');
      });
    }, { rootMargin: '-45% 0px -50% 0px' });

    sections.forEach(function (s) { io.observe(s); });
  })();

  /* ------------------------------------------------------------------ */
  /* 6. Lite YouTube facade                                              */
  /*    No iframe (and no third-party cookies) until the user clicks.    */
  /*    Set data-video-id="<id>" on #video to arm it.                    */
  /* ------------------------------------------------------------------ */
  (function video() {
    var box = $('#video');
    if (!box) return;

    var btn = $('.video__play', box);
    var id  = (box.getAttribute('data-video-id') || '').trim();
    if (!btn) return;

    if (!id) {
      btn.setAttribute('aria-disabled', 'true');
      return;
    }

    $('.video__hint', box) && $('.video__hint', box).remove();

    btn.addEventListener('click', function () {
      var frame = document.createElement('iframe');
      frame.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(id) +
                  '?autoplay=1&rel=0&modestbranding=1';
      frame.title = 'Jalaakar walkthrough';
      frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; picture-in-picture';
      frame.allowFullscreen = true;
      box.classList.add('is-live');
      box.appendChild(frame);
    });
  })();

  /* ------------------------------------------------------------------ */
  /* 7. Signup form                                                      */
  /* ------------------------------------------------------------------ */
  (function signup() {
    var form = $('#signupForm');
    if (!form) return;

    var govNote    = $('#govNote');
    var done       = $('#done');
    var placeInput = $('#place');
    var placeLabel = $('#placeLabel');

    var PLACE_COPY = {
      'farmer':           { label: 'Village / Taluka',            ph: 'Dindori Taluka, Nashik' },
      'society-manager':  { label: 'Housing Society',             ph: 'Shivneri CHS, Kothrud, Pune' },
      'society-resident': { label: 'Housing Society',             ph: 'Shivneri CHS, Kothrud, Pune' },
      'government':       { label: 'Department',                  ph: 'GSDA, Nashik Division' }
    };

    function currentRole() {
      var checked = form.querySelector('input[name="role"]:checked');
      return checked ? checked.value : 'farmer';
    }

    function syncRole() {
      var role = currentRole();
      if (govNote) govNote.classList.toggle('is-relevant', role === 'government');
      var copy = PLACE_COPY[role];
      if (copy && placeInput && placeLabel) {
        placeLabel.textContent  = copy.label;
        placeInput.placeholder  = copy.ph;
      }
    }

    $$('input[name="role"]', form).forEach(function (r) {
      r.addEventListener('change', syncRole);
    });
    syncRole();

    /* ---- validation ---- */
    function setError(field, message) {
      var slot = form.querySelector('[data-error-for="' + field.id + '"]');
      if (slot) slot.textContent = message || '';
      field.setAttribute('aria-invalid', message ? 'true' : 'false');
      return !message;
    }

    function validateName(f) {
      var v = f.value.trim();
      if (!v) return setError(f, 'Please enter your name.');
      if (v.length < 2) return setError(f, 'That name looks too short.');
      return setError(f, '');
    }

    function validatePhone(f) {
      var digits = f.value.replace(/\D/g, '');
      if (!digits) return setError(f, 'We need a number to send WhatsApp alerts to.');

      // Strip the country code by LENGTH, never by prefix. 91 is a real Indian
      // mobile prefix as well as the country code, so /^(0?91|0)/ turns a valid
      // 9123456780 into 8 digits and rejects it. Keep this identical to
      // normalise_phone() in api/appdb.py.
      var local = digits;
      if (digits.length === 13 && digits.indexOf('091') === 0)      local = digits.slice(3);
      else if (digits.length === 12 && digits.indexOf('91') === 0)  local = digits.slice(2);
      else if (digits.length === 11 && digits.indexOf('0') === 0)   local = digits.slice(1);

      if (local.length !== 10 || !/^[6-9]/.test(local)) {
        return setError(f, 'Enter a 10-digit Indian mobile number.');
      }
      return setError(f, '');
    }

    function validatePlace(f) {
      return f.value.trim()
        ? setError(f, '')
        : setError(f, 'Tell us where — this is what we forecast against.');
    }

    function validatePassword(f) {
      /* Same floor as api/appdb.py MIN_PASSWORD. If the two ever disagree the
         browser accepts what the server rejects, which reads as a bug. */
      if (!f.value) return setError(f, 'Choose a password.');
      if (f.value.length < 8) {
        return setError(f, 'At least 8 characters.');
      }
      return setError(f, '');
    }

    var nameInput  = $('#fullName');
    var phoneInput = $('#phone');
    var pwInput    = $('#password');

    [[nameInput, validateName], [phoneInput, validatePhone],
     [placeInput, validatePlace], [pwInput, validatePassword]]
      .forEach(function (pair) {
        var el = pair[0], fn = pair[1];
        if (!el) return;
        el.addEventListener('blur', function () { fn(el); });
        el.addEventListener('input', function () {
          if (el.getAttribute('aria-invalid') === 'true') fn(el);
        });
      });

    form.addEventListener('submit', function (e) {
      e.preventDefault();

      var ok = [
        validateName(nameInput),
        validatePhone(phoneInput),
        validatePlace(placeInput),
        validatePassword(pwInput)
      ].every(Boolean);

      if (!ok) {
        var bad = form.querySelector('[aria-invalid="true"]');
        if (bad) bad.focus();
        if (done) { done.classList.remove('is-on'); done.textContent = ''; }
        return;
      }

      var langEl = form.querySelector('input[name="lang"]:checked');
      var payload = {
        role:  currentRole(),
        name:  nameInput.value.trim(),
        phone: phoneInput.value.trim(),
        place: placeInput.value.trim(),
        password: pwInput.value,
        lang:  langEl ? langEl.value : 'mr'
      };

      var langName = { mr: 'Marathi', hi: 'Hindi', en: 'English' }[payload.lang];
      var btn = form.querySelector('button[type="submit"]');
      var restore = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = 'Creating…'; }

      function finish(msg, isError) {
        if (btn) { btn.disabled = false; btn.textContent = restore; }
        if (!done) return;
        done.textContent = msg;
        done.classList.toggle('auth__done--error', !!isError);
        done.classList.add('is-on');
        done.scrollIntoView({
          behavior: prefersReduced ? 'auto' : 'smooth', block: 'center'
        });
      }

      fetch((window.JALAAKAR_API || '') + '/api/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
        })
        .then(function (res) {
          if (!res.ok) {
            /* The API is the authority on duplicates and on phone shape, so
               its message goes back to the field it belongs to rather than
               being paraphrased. */
            var detail = (res.d && res.d.detail) || 'Something went wrong.';
            if (typeof detail !== 'string') detail = 'Please check your details.';
            if (res.status === 409 || /number/i.test(detail)) {
              setError(phoneInput, detail);
              phoneInput.focus();
              return finish(detail, true);
            }
            return finish(detail, true);
          }

          var d = res.d;
          window.JALAAKAR_USER = d;

          if (d.resolution !== 'ok') {
            /* Registration succeeded but the place did not resolve. Say so —
               a farmer silently subscribed to nothing is worse than an error. */
            return finish(
              'Account created, but we could not match "' + payload.place +
              '" to a monitored taluka yet. We will follow up before your ' +
              'first alert.', true);
          }

          var msg = 'Thanks, ' + payload.name.split(' ')[0] + '. You are ' +
                    'subscribed to ' + d.entity.label + '.';
          if (d.requires_verification) {
            msg += ' Department verification is queued before dashboard access.';
          } else if (d.score && d.score.status === 'ok') {
            msg += ' Current water stress score: ' + d.score.score + '/100 — ' +
                   (d.score.band_label || d.score.band) + '.' +
                   (d.score.days_to_crisis != null
                      ? ' About ' + d.score.days_to_crisis + ' days to crisis.'
                      : '') +
                   ' Alerts will arrive in ' + langName + ' on ' + d.phone + '.';
          } else {
            msg += ' Alerts will arrive in ' + langName + ' on ' + d.phone + '.';
          }
          finish(msg, false);
        })
        .catch(function () {
          /* Offline or backend down. Do not claim an account was created. */
          console.info('[jalaakar] signup payload (not sent)', payload);
          finish('We could not reach the Jalaakar service just now, so your ' +
                 'account was not created. Please try again in a moment.', true);
        });
    });
  })();

  /* ------------------------------------------------------------------ */
  /* 8. Dev sanity check — warn if unverified figures are still on page  */
  /* ------------------------------------------------------------------ */
  (function auditFigures() {
    var unverified = $$('.tag--unverified').length;
    if (unverified) {
      console.warn(
        '[jalaakar] ' + unverified + ' figure(s) on this page are still tagged ' +
        'unverified. Confirm against a primary source or cut them before the demo. ' +
        'See window.JALAAKAR_FIGURES.'
      );
    }
  })();

  /* ------------------------------------------------------------------ */
  /* 9. Hydrate figures from the API                                     */
  /*                                                                     */
  /* The values above are a FALLBACK, not the source of truth. They were */
  /* wrong once already — 6.93% was labelled 30 June when it is 29 June, */
  /* and a retracted 53.38% sat on the page for days. Two hand-kept      */
  /* copies of the same number will always drift, so when the backend is */
  /* reachable the page renders whatever the data says.                  */
  /*                                                                     */
  /* Fails silently and keeps the markup if the API is down: the venue   */
  /* wifi is not something to bet a demo on.                             */
  /* ------------------------------------------------------------------ */
  (function hydrateFigures() {
    if (!window.fetch) return;
    var base = (window.JALAAKAR_API || '') + '/api/figures';

    fetch(base, { headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        var figs = data.figures || {};
        window.JALAAKAR_FIGURES = figs;
        window.JALAAKAR_FIGURES_META = {
          summary: data.summary, retracted: data.retracted, live: true
        };

        var patched = 0, mismatched = [];
        $$('[data-fig]').forEach(function (el) {
          var f = figs[el.getAttribute('data-fig')];
          if (!f || f.value == null) return;
          var shown = parseFloat(el.textContent.replace(/[^0-9.]/g, ''));
          var next = f.value.toFixed(2) + (f.unit === '%' ? '%' : '');
          if (Math.abs(shown - f.value) > 0.005) {
            mismatched.push(el.getAttribute('data-fig') + ': page ' + shown +
                            ' vs data ' + f.value);
          }
          el.textContent = next;
          patched++;
        });

        $$('[data-fig-tag]').forEach(function (el) {
          var f = figs[el.getAttribute('data-fig-tag')];
          if (!f) return;
          var ok = !!f.verified;
          el.classList.toggle('tag--ok', ok);
          el.classList.toggle('tag--unverified', !ok);
          el.textContent = ok ? 'verified • ' + shortSource(f.source_org)
                              : 'unverified';
          if (f.source_url) el.title = f.source_org + ' — ' + f.source_url;
          else if (f.source_org) el.title = f.source_org;
        });

        console.info('[jalaakar] figures hydrated from API (' + patched +
                     ' values). ' + (data.summary
                       ? data.summary.total_anchors + ' anchors, ' +
                         (data.summary.unverified || []).length + ' unverified.'
                       : ''));
        if (mismatched.length) {
          console.warn('[jalaakar] markup disagreed with the data — the page ' +
                       'has been corrected, now fix index.html:\n  ' +
                       mismatched.join('\n  '));
        }
      })
      .catch(function () {
        window.JALAAKAR_FIGURES_META = { live: false };
        console.info('[jalaakar] /api/figures unreachable — using the ' +
                     'hardcoded fallback figures. Fine for an offline demo.');
      });

    function shortSource(s) {
      if (!s) return 'source';
      if (/free press/i.test(s)) return 'FPJ';
      if (/mid-?day/i.test(s)) return 'Mid-Day';
      if (/bmc/i.test(s)) return 'BMC';
      if (/wrd/i.test(s)) return 'WRD';
      if (/punekar/i.test(s)) return 'Punekar';
      if (/bridge/i.test(s)) return 'TBC';
      return s.split(/[\s\/]/)[0];
    }
  })();

  /* ------------------------------------------------------------------ */
  /* 10. Live dashboard                                                  */
  /*                                                                     */
  /* The laptop used to show an invented card: Dindori, 87, Critical,    */
  /* "30 days to empty", well MH-NSK-0412. Scored on real CGWB readings  */
  /* Dindori is 31/100 SAFE and ranks 137th of 164 talukas, and that     */
  /* well ID does not exist. Baglan — same district — genuinely scores   */
  /* 78 ACT NOW, so that is what the demo shows.                         */
  /*                                                                     */
  /* Scenario date is 2023-05-15: CGWB observations end 2023-08-15, so   */
  /* there is no honest rural score for 2026. The API refuses to invent  */
  /* one, which is the correct behaviour and worth saying out loud.      */
  /* ------------------------------------------------------------------ */
  (function liveDashboard() {
    var root = $('[data-dash]');
    if (!root || !window.fetch) return;

    var q = '/api/score?entity_type=taluka&entity_id=Baglan&on=2023-05-15';
    fetch((window.JALAAKAR_API || '') + q, { headers: { Accept: 'application/json' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (card) {
        if (!card || card.status !== 'ok') throw new Error(card && card.reason);
        window.JALAAKAR_CARD = card;

        var d = card.detail || {};
        var slot = function (n) { return $('[data-dash="' + n + '"]'); };
        var set  = function (n, v) { var el = slot(n); if (el) el.textContent = v; };

        set('meta', card.entity_label.replace(' Taluka, ', ' Taluka • ') +
                    ' • ' + d.wells_scored + ' wells');
        set('score', card.score);
        set('state', titleCase(card.band) + ' • ' +
                     (card.days_to_crisis != null
                        ? card.days_to_crisis + ' days to crisis'
                        : 'no crisis projected'));
        var bar = slot('bar');
        if (bar) bar.style.setProperty('--w', card.score + '%');

        set('stat1num', Number(card.headline.value).toFixed(1));
        set('stat1cap', 'm forecast depth');
        set('stat2num', d.days_since_last_reading);
        set('stat2cap', 'days since last reading');

        var notes = slot('notes');
        if (notes) {
          notes.innerHTML = '';
          [ 'Well ' + d.driving_well + ' at ' +
              Number(d.last_obs_level).toFixed(2) + ' m — deepest of ' +
              d.wells_scored,
            'Forecast for ' + fmt(card.target_date) + ', made ' + fmt(card.date)
          ].forEach(function (t) {
            var li = document.createElement('li');
            li.innerHTML = '<i></i><span></span>';
            li.lastChild.textContent = t;
            notes.appendChild(li);
          });
        }

        console.info('[jalaakar] dashboard live from API:', card.entity_label,
                     card.score, card.band, '(' + card.method + ')');
      })
      .catch(function (e) {
        console.info('[jalaakar] /api/score unreachable — dashboard showing ' +
                     'the last real API response, hardcoded in index.html. ' +
                     (e && e.message ? '(' + e.message + ')' : ''));
      });

    function titleCase(s) {
      return String(s || '').toLowerCase().replace(/(^|\s)\w/g, function (m) {
        return m.toUpperCase();
      });
    }
    function fmt(iso) {
      var M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      var p = String(iso || '').split('-');
      return p.length === 3 ? (+p[2]) + ' ' + M[+p[1] - 1] + ' ' + p[0] : iso;
    }
  })();


  /* ------------------------------------------------------------------ */
  /* 11. Sign in (login.html)                                            */
  /*                                                                     */
  /* Writes the token to the same sessionStorage key demo.js reads, so   */
  /* signing in here unlocks the send controls there. sessionStorage,    */
  /* not localStorage: a token should not outlive the browser session on */
  /* a shared demo laptop.                                               */
  /* ------------------------------------------------------------------ */
  (function loginPage() {
    var form = $('#loginForm');
    if (!form) return;

    var phone = $('#loginPhone');
    var pass  = $('#loginPassword');
    var done  = $('#loginDone');
    var btn   = form.querySelector('button[type="submit"]');

    function err(el, msg) {
      var slot = form.querySelector('[data-error-for="' + el.id + '"]');
      if (slot) slot.textContent = msg || '';
      el.setAttribute('aria-invalid', msg ? 'true' : 'false');
      return !msg;
    }

    function finish(msg, isError) {
      if (btn) { btn.disabled = false; btn.textContent = 'Sign in'; }
      done.textContent = msg;
      done.classList.toggle('auth__done--error', !!isError);
      done.classList.add('is-on');
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var ok = [
        phone.value.trim() ? err(phone, '') : err(phone, 'Enter your number.'),
        pass.value ? err(pass, '') : err(pass, 'Enter your password.')
      ].every(Boolean);
      if (!ok) { (form.querySelector('[aria-invalid="true"]') || phone).focus(); return; }

      btn.disabled = true;
      btn.textContent = 'Signing in…';

      fetch((window.JALAAKAR_API || '') + '/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: phone.value.trim(), password: pass.value })
      })
        .then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, d: d }; });
        })
        .then(function (res) {
          if (!res.ok) {
            /* One message for both wrong-number and wrong-password: telling
               them apart turns this form into a way to discover which numbers
               are registered. */
            return finish((res.d && res.d.detail) || 'Could not sign in.', true);
          }
          var u = res.d.user;
          /* Stores the token AND the three fields the nav needs, so every
             page can stop offering "Sign in" to someone who just did. */
          if (window.JALAAKAR) { window.JALAAKAR.save(res.d.token, u); }
          else { try { sessionStorage.setItem('jalaakar_token', res.d.token); } catch (e) {} }
          /* Senders land in the control room, everyone else on the demo.
             An official's first screen should be the state, not a taluka
             picker — and a control room nobody is ever taken to is the same
             defect as the sign-in that only existed inside the alert box. */
          var to = u.can_send ? 'admin.html' : 'demo.html';
          finish('Signed in as ' + u.name + '. ' + (u.can_send
            ? 'Opening the control room…'
            : 'Sending is limited to officials and society managers; opening your score…'), false);
          setTimeout(function () { window.location.href = to; }, 1200);
        })
        .catch(function () {
          finish('Could not reach the Jalaakar service. Try again in a moment.', true);
        });
    });
  })();

})();


/* ==========================================================================
   Shared sign-in state for the nav.

   The nav offered "Sign in" and "Sign up" to everyone, including people who
   had just signed in — on every page, with no way to sign out from any of
   them except the one button buried in the demo's alert box.

   What is stored, and what is not
   -------------------------------
   Only `name`, `role` and `can_send`, and only to decide what the nav says.
   Nothing here is a permission. Every endpoint re-checks the token server
   side, so a tampered blob buys you a link that immediately 401s. Session
   storage, not local: it must not outlive the browser on a shared laptop.
   ========================================================================== */
(function () {
  'use strict';

  var TOKEN_KEY = 'jalaakar_token';
  var USER_KEY = 'jalaakar_user';

  function read(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function write(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  function drop(k) { try { sessionStorage.removeItem(k); } catch (e) { /* ignore */ } }

  function getUser() {
    var s = read(USER_KEY);
    if (!s) { return null; }
    try { return JSON.parse(s); } catch (e) { return null; }
  }

  function save(token, user) {
    if (token) { write(TOKEN_KEY, token); }
    write(USER_KEY, JSON.stringify({
      name: user.name, role: user.role, can_send: !!user.can_send
    }));
  }

  function clear() { drop(TOKEN_KEY); drop(USER_KEY); }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* The signed-out markup is captured once, on first paint, so signing out
     restores exactly what the page shipped with instead of a reconstruction
     that slowly drifts from it. */
  var slots = [];
  Array.prototype.forEach.call(
    document.querySelectorAll('.nav__auth, .nav__auth-mobile'),
    function (el) { slots.push({ el: el, out: el.innerHTML }); });

  function paintNav() {
    var u = getUser();
    slots.forEach(function (s) {
      if (!u) { s.el.innerHTML = s.out; return; }
      var initial = esc((u.name || '?').trim().charAt(0).toUpperCase());
      /* Name and Sign out only. This block used to also inject a "Control
         room" link, which every page already has in its main nav — so the
         header showed it twice. */
      s.el.innerHTML =
        '<span class="nav__me" title="' + esc(u.role || '').replace(/-/g, ' ') + '">' +
        '<span class="nav__me-dot">' + initial + '</span>' +
        '<span class="nav__me-name">' + esc(u.name) + '</span></span>' +
        '<button class="nav__signout" type="button">Sign out</button>';
    });
  }

  function signOut() {
    var t = read(TOKEN_KEY);
    var done = function () {
      clear();
      paintNav();
      /* Always the landing page, never a reload. Reloading leaves a
         signed-out official staring at a locked control room, which reads as
         a failure rather than as a completed sign-out. A full navigation also
         means every page re-derives its state from "no token" — the one path
         that cannot be half-applied. */
      window.location.href = 'index.html';
    };
    if (!t) { done(); return; }
    fetch((window.JALAAKAR_API || '') + '/api/auth/logout', {
      method: 'POST', headers: { Authorization: 'Bearer ' + t }
    }).catch(function () { /* the local session goes either way */ }).then(done);
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.nav__signout');
    if (b) { e.preventDefault(); signOut(); }
  });

  window.JALAAKAR = {
    save: save, clear: clear, getUser: getUser,
    paintNav: paintNav, signOut: signOut, TOKEN_KEY: TOKEN_KEY
  };

  paintNav();
})();
