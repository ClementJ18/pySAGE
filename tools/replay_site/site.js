
(function () {
  var FACTION_SKINS = __FACTION_SKINS__;
  function normalise(name) {
    return String(name == null ? '' : name).toLowerCase().replace(/[^a-z0-9]/g, '');
  }
  var DATA = window.REPLAYS || { rows: [], corpora: [] };
  var rows = DATA.rows, page = 200, shown = page;
  var body = document.querySelector('#table tbody');
  var count = document.getElementById('count');
  var more = document.getElementById('more');
  var sortKey = 'd', sortDir = -1;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function options(select, values) {
    values.forEach(function (v) {
      var o = document.createElement('option');
      o.value = v[0];
      o.textContent = v[1];
      select.appendChild(o);
    });
  }

  // the filter lists are whatever the corpus actually contains, counted as we go
  var byCorpus = {}, byPatch = {}, byMode = {}, byFaction = {};
  rows.forEach(function (r) {
    byCorpus[r.c] = r.cl;
    byPatch[r.g] = (byPatch[r.g] || 0) + 1;
    byMode[r.m] = (byMode[r.m] || 0) + 1;
    r.pl.forEach(function (p) { if (p[1]) byFaction[p[1]] = p[2] || p[1]; });
  });
  options(document.getElementById('f-corpus'),
          Object.keys(byCorpus).sort().map(function (c) { return [c, byCorpus[c]]; }));
  options(document.getElementById('f-patch'),
          Object.keys(byPatch).sort().map(function (g) {
            return [g, g + ' (' + byPatch[g] + ')'];
          }));
  options(document.getElementById('f-mode'),
          Object.keys(byMode).sort().map(function (m) { return [m, m + ' (' + byMode[m] + ')']; }));
  options(document.getElementById('f-faction'),
          Object.keys(byFaction).sort(function (a, b) {
            return byFaction[a].localeCompare(byFaction[b]);
          }).map(function (f) { return [f, byFaction[f]]; }));

  function value(id) { return document.getElementById(id).value.trim().toLowerCase(); }

  function matches(r) {
    var corpus = value('f-corpus'), patch = value('f-patch'), mode = value('f-mode');
    var faction = value('f-faction'), player = value('f-player'), text = value('f-text');
    if (corpus && r.c.toLowerCase() !== corpus) return false;
    if (patch && r.g.toLowerCase() !== patch) return false;
    if (mode && r.m.toLowerCase() !== mode) return false;
    if (faction && !r.pl.some(function (p) { return (p[1] || '').toLowerCase() === faction; }))
      return false;
    if (player && !r.pl.some(function (p) {
      return (p[0] || '').toLowerCase().indexOf(player) >= 0;
    })) return false;
    if (text) {
      var hay = (r.map + ' ' + r.p + ' ' + r.h + ' ' + r.cl + ' ' + r.g).toLowerCase();
      if (hay.indexOf(text) < 0) return false;
    }
    return true;
  }

  function date(seconds) {
    if (!seconds) return '';
    var d = new Date(seconds * 1000);
    return d.toISOString().slice(0, 10);
  }

  function length(seconds) {
    // H:MM:SS, the same shape the aggregate pages use for a match length
    var total = Math.round(seconds), h = Math.floor(total / 3600);
    var m = Math.floor(total % 3600 / 60), s = total % 60;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  function size(bytes) {
    return bytes < 1024 * 1024 ? Math.round(bytes / 1024) + ' KB'
                               : (bytes / 1048576).toFixed(1) + ' MB';
  }

  function teams(r) {
    var wrap = el('div', 'teams'), grouped = {};
    r.pl.forEach(function (p) { (grouped[p[3]] = grouped[p[3]] || []).push(p); });
    Object.keys(grouped).sort().forEach(function (team) {
      var box = el('div', 'team');
      grouped[team].forEach(function (p) {
        var outcome = p[4] === 1 ? ' won' : p[4] === 0 ? ' lost' : '';
        var cls = 'player' + outcome + (p[5] ? ' ai' : '');
        var span = el('span', cls);
        span.appendChild(document.createTextNode(p[0]));
        if (p[2]) {
          var fac = el('span', 'fac', ' ' + p[2]);
          // the faction's own colour, keyed off the raw label so a corpus that renames it
          // in its display map still lands on the right skin
          var slug = FACTION_SKINS[normalise(p[1])] || FACTION_SKINS[normalise(p[2])];
          if (slug) fac.setAttribute('data-fac', slug);
          span.appendChild(fac);
        }
        box.appendChild(span);
      });
      wrap.appendChild(box);
    });
    return wrap;
  }

  function link(href, label, name) {
    var a = el('a', null, label);
    a.href = href.split('/').map(encodeURIComponent).join('/');
    a.setAttribute('download', name);
    return a;
  }

  function render() {
    var found = rows.filter(matches);
    found.sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (typeof x === 'string' || typeof y === 'string')
        return String(x || '').localeCompare(String(y || '')) * sortDir;
      return ((x || 0) - (y || 0)) * sortDir;
    });
    body.innerHTML = '';
    found.slice(0, shown).forEach(function (r) {
      var tr = document.createElement('tr');
      tr.appendChild(el('td', 'date', date(r.d)));
      tr.appendChild(el('td', null, r.cl));
      tr.appendChild(el('td', null, r.g));
      tr.appendChild(el('td', null, r.m));
      var map = el('td', 'map', r.map);
      if (r.x) map.appendChild(el('span', 'crashed', 'crashed'));
      tr.appendChild(map);
      var players = document.createElement('td');
      players.appendChild(teams(r));
      tr.appendChild(players);
      tr.appendChild(el('td', 'len', length(r.s)));
      tr.appendChild(el('td', 'size', size(r.sz)));
      var hash = el('td', 'hash');
      var code = el('code', null, (r.h || '').slice(0, 12));
      code.title = r.h + ' (click to copy)';
      code.addEventListener('click', function () {
        if (navigator.clipboard) navigator.clipboard.writeText(r.h);
        code.textContent = 'copied';
        setTimeout(function () { code.textContent = (r.h || '').slice(0, 12); }, 1000);
      });
      hash.appendChild(code);
      tr.appendChild(hash);
      var name = r.p.split('/').pop();
      var dl = el('td', 'dl');
      dl.appendChild(link('files/' + r.p, 'replay', name));
      dl.appendChild(link('docs/' + r.p + '.json', 'translated', name + '.json'));
      tr.appendChild(dl);
      body.appendChild(tr);
    });
    count.textContent = found.length === rows.length
      ? found.length + ' replays'
      : found.length + ' of ' + rows.length + ' replays';
    more.hidden = found.length <= shown;
    more.textContent = 'Show more (' + (found.length - shown) + ' left)';
  }

  ['f-corpus', 'f-patch', 'f-mode', 'f-faction', 'f-player', 'f-text'].forEach(function (id) {
    var node = document.getElementById(id);
    node.addEventListener('input', function () { shown = page; render(); });
    node.addEventListener('change', function () { shown = page; render(); });
  });
  document.getElementById('f-reset').addEventListener('click', function () {
    ['f-corpus', 'f-patch', 'f-mode', 'f-faction', 'f-player', 'f-text'].forEach(function (id) {
      document.getElementById(id).value = '';
    });
    shown = page;
    render();
  });
  more.addEventListener('click', function () { shown += page; render(); });
  document.querySelectorAll('th[data-sort]').forEach(function (th) {
    th.addEventListener('click', function () {
      var key = th.getAttribute('data-sort');
      sortDir = key === sortKey ? -sortDir : (key === 'd' ? -1 : 1);
      sortKey = key;
      render();
    });
  });
  render();
})();
