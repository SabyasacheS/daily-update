// Watchlist page. Reads watchlist.json (public), writes through the Apps Script (passcode-protected).
(function () {
  var KEY = 'dailyUpdatePasscode';
  var wl = null, filter = 'all', editing = null, endpoint = '';
  var $ = function (id) { return document.getElementById(id); };

  function store(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  function load(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function say(el, text, err) { el.hidden = !text; el.textContent = text || ''; el.className = 'status' + (err ? ' err' : ''); }
  function list(s) { return (s || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean); }

  function call(payload) {
    if (!endpoint) return Promise.reject(new Error('The Apps Script address is not set yet. See SETUP.md, step 5.'));
    payload.passcode = load(KEY) || '';
    // text/plain keeps this a "simple" request, so the browser sends it without a preflight.
    return fetch(endpoint, { method: 'POST', body: JSON.stringify(payload) })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (!d.ok) throw new Error(d.error || 'Request refused'); return d; });
  }

  function sectionLabel(id) { var s = wl.sections.filter(function (x) { return x.id === id; })[0]; return s ? s.label : id; }

  function render() {
    var cos = wl.companies;
    $('wl-count').textContent = cos.length + ' names tracked';
    var pills = [{ id: 'all', label: 'All' }].concat(wl.sections);
    $('wl-pills').innerHTML = pills.map(function (p) {
      var n = p.id === 'all' ? cos.length : cos.filter(function (c) { return c.sections.indexOf(p.id) >= 0; }).length;
      return '<button type="button" data-f="' + p.id + '" aria-pressed="' + (p.id === filter) + '">' + esc(p.label) + ' · ' + n + '</button>';
    }).join('');
    var shown = filter === 'all' ? cos : cos.filter(function (c) { return c.sections.indexOf(filter) >= 0; });
    var unlocked = !!load(KEY);
    $('wl-rows').innerHTML = shown.map(function (c) {
      var i = cos.indexOf(c);
      var type = c.ticker ? 'Listed · ' + esc(c.ticker) : 'Private';
      var acts = unlocked ? '<button class="btn btn-ghost" type="button" data-edit="' + i + '">Edit</button>' +
        '<button class="btn btn-ghost" type="button" data-del="' + i + '" aria-label="Remove ' + esc(c.name) + '">Remove</button>' : '';
      return '<div class="wl-row"><span class="nm">' + esc(c.name) + (c.valuation && c.valuation.pinned ? ' <span class="tag">PINNED</span>' : '') + '</span>' +
        '<span class="secs">' + c.sections.map(function (s) { return '<span>' + esc(sectionLabel(s)) + '</span>'; }).join('') + '</span>' +
        '<span class="tp">' + type + '</span>' + acts + '</div>';
    }).join('');
    $('f-secs').innerHTML = wl.sections.map(function (s) {
      return '<label><input type="checkbox" value="' + s.id + '"> ' + esc(s.label) + '</label>';
    }).join('');
    $('lock-panel').hidden = unlocked;
    $('edit-panel').hidden = !unlocked;
    $('refresh-panel').hidden = !unlocked;
  }

  function parseValuation(t) {
    var m = /(c\.\s*)?([A-Z]{3})\s*([\d.,]+)\s*(tn|bn|m)?/i.exec(t || '');
    if (!m) return null;
    var mult = { tn: 1e12, bn: 1e9, m: 1e6 }[(m[4] || '').toLowerCase()] || 1;
    return { text: t.trim(), amount: parseFloat(m[3].replace(/,/g, '')) * mult, currency: m[2].toUpperCase(),
      status: 'manual', approx: !!m[1], pinned: true };
  }

  function fillForm(c) {
    editing = c ? c.name : null;
    $('form-title').textContent = c ? 'Edit ' + c.name : 'Add a company';
    $('f-name').value = c ? c.name : '';
    $('f-domain').value = c ? (c.domain || '') : '';
    $('f-ticker').value = c ? (c.ticker || '') : '';
    $('f-ccy').value = c ? (c.currency || '') : '';
    $('f-aliases').value = c && c.aliases ? c.aliases.join(', ') : '';
    $('f-must').value = c && c.must ? c.must.join(', ') : '';
    $('f-val').value = c && c.valuation && c.valuation.pinned ? c.valuation.text : '';
    Array.prototype.forEach.call($('f-secs').querySelectorAll('input'), function (b) { b.checked = !!(c && c.sections.indexOf(b.value) >= 0); });
    $('cancel-edit').hidden = !c;
    if (c) $('f-name').focus();
  }

  function save() {
    var name = $('f-name').value.trim();
    var secs = Array.prototype.filter.call($('f-secs').querySelectorAll('input'), function (b) { return b.checked; }).map(function (b) { return b.value; });
    if (!name) return say($('form-msg'), 'Enter a company name.', true);
    if (!secs.length) return say($('form-msg'), 'Pick at least one section.', true);
    var vt = $('f-val').value.trim(), val = null;
    if (vt) { val = parseValuation(vt); if (!val) return say($('form-msg'), 'Write the valuation like "USD 12bn" or "c. EUR 800m".', true); }
    var company = { name: name, sections: secs, domain: $('f-domain').value.trim().replace(/^https?:\/\//, '').replace(/\/$/, ''),
      ticker: $('f-ticker').value.trim().toUpperCase(), currency: $('f-ccy').value.trim().toUpperCase(),
      aliases: list($('f-aliases').value), must: list($('f-must').value) };
    if (!company.aliases.length) company.aliases = [name];
    $('save').disabled = true;
    say($('form-msg'), 'Saving…');
    call({ action: 'upsertCompany', company: company, previousName: editing, valuation: val, clearValuation: !vt })
      .then(function () {
        var i = wl.companies.map(function (c) { return c.name; }).indexOf(editing || name);
        var merged = Object.assign({}, i >= 0 ? wl.companies[i] : {}, company);
        if (val) merged.valuation = val; else if (merged.valuation && merged.valuation.pinned) delete merged.valuation;
        if (i >= 0) wl.companies[i] = merged; else wl.companies.unshift(merged);
        say($('form-msg'), 'Saved ' + name + '. The report is rebuilding and will include it in about 3 minutes.');
        fillForm(null); render();
      })
      .catch(function (e) { say($('form-msg'), e.message, true); })
      .then(function () { $('save').disabled = false; });
  }

  function remove(i) {
    var c = wl.companies[i];
    if (!window.confirm('Remove ' + c.name + ' from the watchlist?')) return;
    call({ action: 'removeCompany', name: c.name })
      .then(function () { wl.companies.splice(i, 1); render(); say($('form-msg'), 'Removed ' + c.name + '. It drops out of the next report.'); })
      .catch(function (e) { say($('form-msg'), e.message, true); });
  }

  document.addEventListener('click', function (e) {
    var t = e.target;
    if (t.dataset.f) { filter = t.dataset.f; render(); }
    else if (t.dataset.edit) { fillForm(wl.companies[+t.dataset.edit]); }
    else if (t.dataset.del) { remove(+t.dataset.del); }
  });
  $('unlock').addEventListener('click', function () {
    var p = $('pass').value;
    if (!p) return say($('lock-msg'), 'Enter the passcode.', true);
    store(KEY, p);
    call({ action: 'verify' })
      .then(function () { say($('lock-msg'), ''); render(); })
      .catch(function (e) { store(KEY, null); say($('lock-msg'), e.message, true); });
  });
  $('pass').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('unlock').click(); });
  $('save').addEventListener('click', save);
  $('cancel-edit').addEventListener('click', function () { fillForm(null); });
  $('refresh').addEventListener('click', function () {
    say($('refresh-msg'), 'Starting…');
    call({ action: 'refresh' })
      .then(function () { say($('refresh-msg'), 'Refresh started. Reload the report in about 3 minutes.'); })
      .catch(function (e) { say($('refresh-msg'), e.message, true); });
  });

  fetch('watchlist.json', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (d) { wl = d; endpoint = (d.settings || {}).apps_script_url || ''; render(); })
    .catch(function () { $('wl-count').textContent = 'Could not load the watchlist. Reload the page.'; });
})();
