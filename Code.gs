/**
 * Daily Update — Watchlist backend (Google Apps Script, free).
 *
 * The public Watchlist page posts changes here with a passcode. This script edits
 * watchlist.json in your GitHub repo and starts a refresh run (without email).
 *
 * Script properties to set (Project Settings → Script properties):
 *   PASSCODE      the passcode you give to people allowed to edit
 *   GITHUB_TOKEN  fine-grained token with "Contents: Read and write" on this repo only
 *   REPO          owner/repo, e.g. sabyasaches/Project-Megatron---Daily-Update
 *   BRANCH        main (optional)
 */
function props_() { return PropertiesService.getScriptProperties(); }
function out_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }

function doGet() { return out_({ ok: true, service: 'daily-update-watchlist' }); }

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents || '{}');
    var p = props_();
    if (!p.getProperty('PASSCODE') || req.passcode !== p.getProperty('PASSCODE')) {
      Utilities.sleep(800); // slow down guessing
      return out_({ ok: false, error: 'Wrong passcode.' });
    }
    switch (req.action) {
      case 'verify': return out_({ ok: true });
      case 'refresh': dispatch_(); return out_({ ok: true });
      case 'upsertCompany': return out_(upsert_(req));
      case 'removeCompany': return out_(remove_(req.name));
      default: return out_({ ok: false, error: 'Unknown action.' });
    }
  } catch (err) {
    return out_({ ok: false, error: String(err.message || err) });
  }
}

function gh_(method, path, body) {
  var p = props_();
  var res = UrlFetchApp.fetch('https://api.github.com/repos/' + p.getProperty('REPO') + path, {
    method: method, muteHttpExceptions: true, contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + p.getProperty('GITHUB_TOKEN'), Accept: 'application/vnd.github+json' },
    payload: body ? JSON.stringify(body) : null
  });
  var code = res.getResponseCode();
  if (code >= 300) throw new Error('GitHub said ' + code + ': ' + res.getContentText().slice(0, 200));
  var text = res.getContentText();
  return text ? JSON.parse(text) : {};
}

function readWatchlist_() {
  var branch = props_().getProperty('BRANCH') || 'main';
  var f = gh_('get', '/contents/watchlist.json?ref=' + branch);
  var json = Utilities.newBlob(Utilities.base64Decode(f.content.replace(/\n/g, ''))).getDataAsString('UTF-8');
  return { data: JSON.parse(json), sha: f.sha, branch: branch };
}

function writeWatchlist_(w, message) {
  var text = JSON.stringify(w.data, null, 2) + '\n';
  gh_('put', '/contents/watchlist.json', {
    message: message, sha: w.sha, branch: w.branch,
    content: Utilities.base64Encode(text, Utilities.Charset.UTF_8)
  });
  dispatch_();
}

function dispatch_() {
  gh_('post', '/dispatches', { event_type: 'watchlist-updated' });
}

function clean_(c) {
  var str = function (s, n) { return String(s || '').trim().slice(0, n || 120); };
  var arr = function (a) { return (a || []).map(function (x) { return str(x, 60); }).filter(String).slice(0, 12); };
  return {
    name: str(c.name), sections: arr(c.sections), domain: str(c.domain).toLowerCase(),
    ticker: str(c.ticker, 20).toUpperCase(), currency: str(c.currency, 3).toUpperCase(),
    aliases: arr(c.aliases), must: arr(c.must)
  };
}

function upsert_(req) {
  var c = clean_(req.company || {});
  if (!c.name) return { ok: false, error: 'Name is required.' };
  if (!c.sections.length) return { ok: false, error: 'Pick at least one section.' };
  var w = readWatchlist_();
  var list = w.data.companies;
  var key = (req.previousName || c.name).toLowerCase();
  var i = -1;
  for (var k = 0; k < list.length; k++) if (list[k].name.toLowerCase() === key) { i = k; break; }
  var merged = i >= 0 ? list[i] : {};
  Object.keys(c).forEach(function (f) {
    if (c[f] !== '' && !(Array.isArray(c[f]) && !c[f].length)) merged[f] = c[f];
    else if (f === 'ticker' || f === 'domain' || f === 'must') merged[f] = c[f];
  });
  if (!merged.aliases || !merged.aliases.length) merged.aliases = [c.name];
  if (req.valuation) merged.valuation = req.valuation;
  else if (req.clearValuation && merged.valuation && merged.valuation.pinned) delete merged.valuation;
  if (i >= 0) list[i] = merged; else list.push(merged);
  writeWatchlist_(w, (i >= 0 ? 'Update ' : 'Add ') + c.name + ' via Watchlist page');
  return { ok: true };
}

function remove_(name) {
  var w = readWatchlist_();
  var before = w.data.companies.length;
  w.data.companies = w.data.companies.filter(function (c) { return c.name !== name; });
  if (w.data.companies.length === before) return { ok: false, error: 'Not found: ' + name };
  writeWatchlist_(w, 'Remove ' + name + ' via Watchlist page');
  return { ok: true };
}
