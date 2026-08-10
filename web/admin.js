/* ==========================================================================
   JALAAKAR — control room.

   One page, two jobs: show an official where the state stands, and let them
   act on it. Everything here is a thin skin over /api/admin/*; no scoring,
   no band logic and no thresholds live in this file, because a cutoff that
   exists in two places is a cutoff that will disagree with itself.

   Session state is shared with every other page through window.JALAAKAR
   (defined in script.js), so signing in anywhere unlocks everywhere and the
   nav stops offering "Sign in" to someone who already has.
   ========================================================================== */
(function () {
  'use strict';

  var API = '';
  var S = window.JALAAKAR || null;

  var $ = function (s) { return document.querySelector(s); };
  var token = null;
  try { token = sessionStorage.getItem('jalaakar_token'); } catch (e) { token = null; }

  var snapshot = null;      // last /api/admin/overview payload
  var bucket = 'all';
  var busy = false;

  function headers(json) {
    var h = {};
    if (token) { h.Authorization = 'Bearer ' + token; }
    if (json) { h['Content-Type'] = 'application/json'; }
    return h;
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* ------------------------------------------------------------ requests */
  /* Every failure mode gets its OWN message, because "Could not reach the
     API" was being printed for four unrelated things — a dead server, an
     expired token, a 500, and a TypeError in this file's own rendering. A
     message that covers everything diagnoses nothing. `status` is carried on
     the error so callers can tell "signed out" from "broken". */
  function request(path, opts) {
    return fetch(API + path, opts).then(
      function (r) {
        return r.text().then(function (txt) {
          var data = null;
          try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
          if (!r.ok) {
            var detail = data && (data.detail || data.message);
            if (detail && typeof detail !== 'string') { detail = JSON.stringify(detail); }
            var err = new Error(detail || ('The server replied ' + r.status +
              (r.statusText ? ' ' + r.statusText : '') + '.'));
            err.status = r.status;
            throw err;
          }
          if (data === null) {
            var bad = new Error('The server replied ' + r.status +
              ' but the body was not JSON this page could read.');
            bad.status = r.status;
            throw bad;
          }
          return data;
        });
      },
      function () {
        /* fetch only rejects on a genuine transport failure. The commonest
           cause here is not a crashed server — it is opening the file
           directly, where a relative /api/ path resolves to file:// */
        var e = new Error('No reply from the server. Check it is running, ' +
          'and that you opened this page from http://localhost:8000 rather ' +
          'than by double-clicking the HTML file.');
        e.status = 0;
        throw e;
      }
    );
  }

  function signedOut(e) { return e.status === 401 || e.status === 403; }

  function forget() {
    try { sessionStorage.removeItem('jalaakar_token'); } catch (x) { /* ignore */ }
    token = null;
    if (S) { S.clear(); S.paintNav(); }
  }

  function bandClass(band) {
    return band === 'ACT NOW' ? 'act-now' : band === 'MONITOR' ? 'monitor' : 'safe';
  }

  /* "1,183 days ago" reads as a fact; "1183" reads as a serial number. And
     staleness is the single most important caveat on the rural track, so it
     gets words rather than a bare integer. */
  function ageWords(days) {
    if (days === null || days === undefined) { return ''; }
    if (days <= 1) { return 'today'; }
    if (days < 60) { return days + ' days ago'; }
    if (days < 730) { return Math.round(days / 30.4) + ' months ago'; }
    return (days / 365.25).toFixed(1) + ' years ago';
  }

  /* ---------------------------------------------------------------- gate */
  function lock(message) {
    $('#admBody').hidden = true;
    $('#admLocked').hidden = false;
    $('#admErr').textContent = message || '';
  }

  /* Who is signed in is the nav's job, on every page. This function only
     decides whether the page shows the state or the locked card. */
  function unlock() {
    $('#admLocked').hidden = true;
    $('#admBody').hidden = false;
  }

  function boot() {
    if (!token) {
      forget();
      lock('You are not signed in.');
      return;
    }
    request('/api/auth/me', { headers: headers() })
      .then(function (d) {
        var u = d.user || {};
        /* can_send is the server's own answer to "may this account act?".
           Re-deriving it here from role and verified would be a second copy
           of the rule, and the two would drift. */
        if (!u.can_send) {
          if (S) { S.save(null, u); S.paintNav(); }
          lock(u.role === 'government' && !u.verified
            ? 'This government account is still awaiting department verification.'
            : 'This account is registered as a ' +
              String(u.role || 'user').replace(/-/g, ' ') + '.');
          return;
        }
        if (S) { S.save(null, u); S.paintNav(); }
        unlock();
        load(false);
      })
      .catch(function (e) {
        if (signedOut(e)) { forget(); lock('Your session has expired. Sign in again.'); }
        else { lock(e.message); }
        if (window.console) { console.error('[jalaakar] auth check failed', e); }
      });
  }

  /* ------------------------------------------------------------- loading */
  function fail(e, where) {
    if (window.console) { console.error('[jalaakar] ' + where + ' failed', e); }
    if (signedOut(e)) {
      forget();
      lock('Your session has expired. Sign in again.');
      return;
    }
    $('#admMeta').textContent = e.message;
    $('#admRows').innerHTML = '<tr><td class="adm__empty" colspan="6">' +
      esc(e.message) + '</td></tr>';
  }

  function load(refresh) {
    if (busy) { return; }
    busy = true;
    var btn = $('#admRefresh');
    btn.disabled = true;
    btn.textContent = refresh ? 'Rescoring…' : 'Scoring…';
    $('#admMeta').textContent = refresh
      ? 'Rescoring every taluka and reservoir…'
      : 'Scoring the state…';

    request('/api/admin/overview?bucket=all' + (refresh ? '&refresh=true' : ''),
            { headers: headers() })
      .then(function (d) {
        snapshot = d;
        /* A thrown TypeError in here is a bug in THIS file, not a server
           problem, and it must not be reported as one. */
        try {
          paintTiles(d);
          paintMeta(d);
          paintRows();
        } catch (err) {
          var e = new Error('The server returned ' + (d.total || 0) +
            ' places, but this page could not draw them: ' + err.message);
          e.status = 200;
          throw e;
        }
      })
      .catch(function (e) { fail(e, 'overview'); })
      .then(function () {
        busy = false;
        btn.disabled = false;
        btn.textContent = 'Rescore';
      });
  }

  function paintMeta(d) {
    /* The snapshot is cached, so its age has to be visible. A number with no
       stated age is the thing this project keeps refusing to ship. */
    var age = d.age_seconds < 5 ? 'just now'
      : d.age_seconds < 90 ? d.age_seconds + 's ago'
        : Math.round(d.age_seconds / 60) + ' min ago';
    var model = d.model === 'xgboost'
      ? 'trained XGBoost model'
      : 'climatology fallback — the model did not load';
    $('#admMeta').innerHTML =
      esc(d.total) + ' places · scored ' + esc(age) +
      ' in ' + esc(d.build_seconds) + 's · ' +
      '<span class="' + (d.model === 'xgboost' ? 'adm__on' : 'adm__off') + '">' +
      esc(model) + '</span>';
  }

  function paintTiles(d) {
    var c = d.counts, r = d.subscriber_reach;
    $('#tAct').textContent = c.act_now;
    $('#tMon').textContent = c.monitor;
    $('#tSafe').textContent = c.safe;
    $('#tNone').textContent = c.unscorable;
    $('#tActReach').textContent = r.act_now;
    $('#tMonReach').textContent = r.monitor;
  }

  function visibleRows() {
    if (!snapshot) { return []; }
    var q = ($('#admFind').value || '').trim().toLowerCase();
    return snapshot.rows.filter(function (x) {
      var b = x.score === null ? 'unscorable'
        : x.band === 'ACT NOW' ? 'act_now'
          : x.band === 'MONITOR' ? 'monitor' : 'safe';
      if (bucket !== 'all' && b !== bucket) { return false; }
      if (!q) { return true; }
      return (x.label + ' ' + (x.district || '') + ' ' + x.entity_id)
        .toLowerCase().indexOf(q) >= 0;
    });
  }

  function paintRows() {
    var rows = visibleRows();
    var body = $('#admRows');

    if (!rows.length) {
      body.innerHTML = '<tr><td class="adm__empty" colspan="6">' +
        (snapshot ? 'Nothing in this bucket. That is a result, not an error.'
                  : 'Nothing loaded yet.') + '</td></tr>';
      $('#admFoot').textContent = '';
      syncSend(rows);
      return;
    }

    /* Capped at 120 rows. 247 talukas of DOM is a scroll nobody performs, and
       the buckets plus the filter are the intended way to narrow it. */
    var shown = rows.slice(0, 120);
    body.innerHTML = shown.map(function (x) {
      var cls = x.score === null ? 'none' : bandClass(x.band);
      var score = x.score === null ? '—' : x.score;
      var reading = x.date
        ? esc(x.date) + '<em>' + esc(ageWords(x.days_stale)) + '</em>'
        : '<em>' + esc((x.reason || 'no reading').slice(0, 60)) + '</em>';
      return '<tr class="adm__r adm__r--' + cls + '">' +
        '<td><b class="adm__score adm__score--' + cls + '">' + esc(score) + '</b></td>' +
        '<td class="adm__place">' + esc(x.label) +
        (x.n_wells ? '<em>' + esc(x.n_wells) +
          (x.n_wells === 1 ? ' well' : ' wells') + '</em>' : '') + '</td>' +
        '<td><span class="adm__track adm__track--' + esc(x.track) + '">' +
        esc(x.track) + '</span></td>' +
        '<td class="adm__when">' + reading + '</td>' +
        '<td>' + (x.days_to_crisis === null || x.days_to_crisis === undefined
          ? '<span class="adm__dim">—</span>' : esc(x.days_to_crisis)) + '</td>' +
        '<td>' + (x.subscribers
          ? '<b>' + esc(x.subscribers) + '</b>'
          : '<span class="adm__dim">0</span>') + '</td>' +
        '</tr>';
    }).join('');

    $('#admFoot').textContent = rows.length > shown.length
      ? 'Showing the worst ' + shown.length + ' of ' + rows.length +
        ' — narrow it with the filter.'
      : 'Showing all ' + rows.length + '.';

    syncSend(rows);
  }

  /* The Send button's count is the number of PEOPLE, not places. An official
     about to message the public should see how many phones will ring. */
  function syncSend(rows) {
    /* SAFE and unscorable places can never be alerted, so their subscribers
       must not be counted toward the button. */
    var live = rows.reduce(function (a, x) {
      return a + (x.band === 'ACT NOW' || x.band === 'MONITOR' ? (x.subscribers || 0) : 0);
    }, 0);
    $('#admReach').textContent = live;
    $('#admSend').disabled = live === 0;
    $('#admSend').title = live === 0
      ? 'Nobody in this bucket is registered, so there is no one to message.'
      : 'Message ' + live + (live === 1 ? ' subscriber' : ' subscribers');

    /* The single-number send targets the worst ALERTABLE place in view. A
       SAFE place would produce an all-clear, which is not what a button
       labelled "send an alert" should do. */
    one = null;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].band === 'ACT NOW' || rows[i].band === 'MONITOR') {
        one = rows[i];
        break;
      }
    }
    $('#admOneGo').disabled = !one;
    $('#admOneFor').textContent = one
      ? 'Sends the ' + (one.band === 'ACT NOW' ? 'caution alert' : 'notice') +
        ' for ' + one.label + ' — ' + one.score + '/100, ' + one.band +
        '. Change the filter above to pick a different place.'
      : 'Nothing in this view warrants an alert, so there is nothing to send.';
    return live;
  }

  /* ------------------------------------------------------------ preview */
  /* Shows the WORDING, not the recipient list. Both bands, both audience
     types, all three languages — the question before pressing Send is "what
     will this say", and the recipient list only answers "who". The bodies
     come from /api/admin/preview, which renders them with the same
     alerts.render the real send calls, so this cannot drift from what goes
     out. */
  var pv = null, pvBand = 'ACT NOW', pvRole = 'farmer', pvLang = 'mr';
  var one = null;   // worst alertable row in the current view

  function paintPreview() {
    if (!pv) { return; }
    var body = ((pv.messages[pvBand] || {})[pvRole] || {})[pvLang];
    $('#admPvBody').textContent = body || 'No template for this combination.';
    $('#admPvBody').setAttribute('lang', pvLang);
    $('#admPvTime').textContent = new Date().toLocaleTimeString([], {
      hour: '2-digit', minute: '2-digit'
    });
    var s = pv.sample[pvBand] || {};
    $('#admPvNote').textContent =
      'Sample only — ' + pv.sample.place + ', score ' + s.score + ', ' +
      s.days + ' days. Every recipient gets their own place, score and days, ' +
      'in the language they signed up in. ' + pv.review_status + '.';
  }

  function toggle(selector, attr, set) {
    Array.prototype.forEach.call(document.querySelectorAll(selector), function (b) {
      b.addEventListener('click', function () {
        set(b.getAttribute(attr));
        Array.prototype.forEach.call(document.querySelectorAll(selector), function (o) {
          o.classList.toggle('is-on', o === b);
          o.setAttribute('aria-selected', o === b ? 'true' : 'false');
        });
        paintPreview();
      });
    });
  }

  toggle('.adm__pvband', 'data-band', function (v) { pvBand = v; });
  toggle('.adm__pvrole', 'data-role', function (v) { pvRole = v; });
  toggle('.adm__pvlang', 'data-pvlang', function (v) { pvLang = v; });

  function preview() {
    var btn = $('#admPreview');
    var was = btn.textContent;
    /* A second click closes it — it is a panel, not a one-way door. */
    if (!$('#admPv').hidden) { $('#admPv').hidden = true; return; }
    btn.disabled = true;
    btn.textContent = 'Loading…';
    $('#admSendNote').textContent = '';

    var got = pv ? Promise.resolve(pv)
                 : request('/api/admin/preview', { headers: headers() });
    got.then(function (d) {
      pv = d;
      $('#admPv').hidden = false;
      paintPreview();
    })
      .catch(function (e) {
        if (window.console) { console.error('[jalaakar] preview failed', e); }
        if (signedOut(e)) { forget(); lock('Your session has expired. Sign in again.'); return; }
        $('#admSendNote').textContent = e.message;
        $('#admSendNote').className = 'adm__note adm__note--warn';
      })
      .then(function () {
        btn.disabled = false;
        btn.textContent = was;
      });
  }

  /* --------------------------------------------------------------- send */
  function cast(dryRun) {
    var btn = dryRun ? $('#admPreview') : $('#admSend');
    var was = btn.textContent;
    btn.disabled = true;
    btn.textContent = dryRun ? 'Rendering…' : 'Sending…';
    $('#admSendNote').textContent = '';

    request('/api/admin/broadcast', {
      method: 'POST',
      headers: headers(true),
      body: JSON.stringify({ bucket: bucket, dry_run: !!dryRun })
    })
      .then(paintResult)
      .catch(function (e) {
        if (window.console) { console.error('[jalaakar] broadcast failed', e); }
        if (signedOut(e)) { forget(); lock('Your session has expired. Sign in again.'); return; }
        $('#admSendNote').textContent = e.message;
        $('#admSendNote').className = 'adm__note adm__note--warn';
      })
      .then(function () {
        btn.disabled = false;
        btn.textContent = was;
      });
  }

  function paintResult(d) {
    var list = $('#admResult');
    list.hidden = false;

    list.innerHTML = d.detail.sent.concat(d.detail.failed).map(function (x) {
      var st = x.status === 'preview' ? 'preview'
        : x.status === 'sent' ? 'delivered'
          : x.status === 'rendered' ? 'logged, not delivered' : x.status;
      return '<li>' +
        '<span class="cast__band cast__band--' + bandClass(x.band) + '">' +
        esc(x.score) + '</span>' +
        '<span class="cast__who">' + esc(x.name || x.user_id) + ' · ' +
        esc(x.entity) + ' · ' + esc(x.lang) + '</span>' +
        '<span class="cast__st">' + esc(st) + '</span>' +
        '</li>';
    }).join('') || '<li><span class="cast__who">Nobody matched.</span></li>';

    var note;
    if (d.dry_run) {
      note = 'Preview only — nothing was sent and nothing was logged. ' +
        d.caution + ' would get the caution alert, ' + d.notice +
        ' the ordinary notice, and ' + d.skipped + ' would not be contacted.';
      $('#admSendNote').className = 'adm__note';
    } else if (d.delivered === d.sent && d.sent > 0) {
      note = d.sent + ' delivered over WhatsApp — ' + d.caution +
        ' caution, ' + d.notice + ' notice. ' + d.skipped + ' skipped.';
      $('#admSendNote').className = 'adm__note adm__note--ok';
    } else {
      /* Never dressed up as a delivery. This is the same rule the API keeps. */
      note = d.sent + ' message(s) rendered and written to the alert log, but ' +
        (d.delivered ? (d.sent - d.delivered) + ' of them were ' : '') +
        'NOT delivered — WhatsApp credentials are not configured on this server. ' +
        d.skipped + ' skipped.';
      $('#admSendNote').className = 'adm__note adm__note--warn';
    }
    if (d.failed) { note += ' ' + d.failed + ' failed.'; }
    $('#admSendNote').textContent = note;
  }

  /* -------------------------------------------------------------- wiring */
  Array.prototype.forEach.call(document.querySelectorAll('.adm__tab'), function (t) {
    t.addEventListener('click', function () {
      bucket = t.getAttribute('data-bucket');
      Array.prototype.forEach.call(document.querySelectorAll('.adm__tab'), function (o) {
        o.classList.toggle('is-on', o === t);
        o.setAttribute('aria-selected', o === t ? 'true' : 'false');
      });
      $('#admResult').hidden = true;
      $('#admSendNote').textContent = '';
      /* Follow the bucket the official is looking at, so the panel is never
         showing the caution wording while the table is filtered to 41-70. */
      if (bucket === 'act_now' || bucket === 'monitor') {
        pvBand = bucket === 'act_now' ? 'ACT NOW' : 'MONITOR';
        Array.prototype.forEach.call(
          document.querySelectorAll('.adm__pvband'), function (o) {
            var on = o.getAttribute('data-band') === pvBand;
            o.classList.toggle('is-on', on);
            o.setAttribute('aria-selected', on ? 'true' : 'false');
          });
        paintPreview();
      }
      paintRows();
    });
  });

  $('#admFind').addEventListener('input', paintRows);
  $('#admRefresh').addEventListener('click', function () { load(true); });
  $('#admPreview').addEventListener('click', preview);
  $('#admSend').addEventListener('click', function () { cast(false); });

  /* One phone, one place — the "it lands on a real handset" moment, moved off
     the demo page so that page can be identical for every visitor. Uses
     /api/alerts/send-demo, which is gated to the same senders. */
  $('#admOneGo').addEventListener('click', function () {
    var out = $('#admOneNote');
    var phone = ($('#admOnePhone').value || '').trim();
    if (!one) { return; }
    if (!phone) {
      out.textContent = 'Enter a number first.';
      out.className = 'adm__note adm__note--warn';
      return;
    }
    var btn = $('#admOneGo');
    var was = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Sending…';
    out.textContent = '';

    request('/api/alerts/send-demo', {
      method: 'POST',
      headers: headers(true),
      body: JSON.stringify({
        entity_type: one.entity_type, entity_id: one.entity_id,
        on: one.date, lang: pvLang,
        role: one.track === 'urban' ? 'society-manager' : 'farmer',
        /* An explicit human pressing Send is an instruction, so it goes even
           if the band would not trigger the automatic path. */
        force: true, phone: phone
      })
    })
      .then(function (d) {
        if (d.status === 'sent') {
          out.textContent = 'Delivered to ' + d.to + ' — check the phone.' +
            (d.provider_sid ? ' (' + d.provider_sid + ')' : '');
          out.className = 'adm__note adm__note--ok';
        } else if (d.status === 'rendered') {
          /* Never dress a dry run up as a delivery. */
          out.textContent = 'Rendered and written to the alert log for ' +
            d.to + ', but NOT delivered — WhatsApp credentials are not ' +
            'configured on this server.';
          out.className = 'adm__note adm__note--warn';
        } else {
          out.textContent = 'Send failed: ' + (d.error || d.status);
          out.className = 'adm__note adm__note--warn';
        }
      })
      .catch(function (e) {
        if (window.console) { console.error('[jalaakar] single send failed', e); }
        if (signedOut(e)) { forget(); lock('Your session has expired. Sign in again.'); return; }
        out.textContent = e.message;
        out.className = 'adm__note adm__note--warn';
      })
      .then(function () { btn.disabled = false; btn.textContent = was; });
  });

  /* No sign-out handler here. Signing out is one behaviour for the whole
     site, defined once in script.js and reachable from the nav on every
     page. A second button wired to a second implementation is how the two
     drift apart. */

  boot();
})();
