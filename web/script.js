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
    mumbai7Lakes_30Jun2026: { value: 6.93,  unit: '%', verified: true,
      source: "BMC Hydraulic Engineer's Department" },
    mumbai7Lakes_07Aug2026: { value: 88.50, unit: '%', verified: true,
      source: 'mumbailakewaterlevel.in' },
    pune5Dams_07Aug2026:    { value: 96.60, unit: '%', verified: true,
      source: 'Maharashtra WRD / Pravah' },

    mumbai_16Jun2026:       { value: 10.35, unit: '%', verified: false, source: null },
    mumbai_23Jun2026:       { value: 8.34,  unit: '%', verified: false, source: null },
    statewide_25Jun2026:    { value: 53.38, unit: '%', verified: false, source: null },

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
      // Indian mobile: 10 digits, optionally prefixed with 91 or 091
      var local = digits.replace(/^(0?91|0)/, '');
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

    var nameInput  = $('#fullName');
    var phoneInput = $('#phone');

    [[nameInput, validateName], [phoneInput, validatePhone], [placeInput, validatePlace]]
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
        validatePlace(placeInput)
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
        lang:  langEl ? langEl.value : 'mr'
      };

      // No backend yet — surface the payload so the demo can show what
      // would be POSTed to /api/signup.
      console.info('[jalaakar] signup payload', payload);

      if (done) {
        var langName = { mr: 'Marathi', hi: 'Hindi', en: 'English' }[payload.lang];
        done.textContent =
          'Thanks, ' + payload.name.split(' ')[0] + '. ' +
          (payload.role === 'government'
            ? 'Your department verification request has been queued.'
            : 'Your first ' + langName + ' alert will reach ' + payload.phone + ' within 24 hours.');
        done.classList.add('is-on');
        done.scrollIntoView({ behavior: prefersReduced ? 'auto' : 'smooth', block: 'center' });
      }
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

})();
