
(function () {
  var body = document.body, root = document.documentElement;
  var base = root.getAttribute('data-base') || '';
  var active = root.getAttribute('data-active') || '';
  var W = window.WIKI;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // sidebar: the fixed pages, then one collapsible section per module group
  var nav = document.getElementById('nav');
  var pages = el('div', 'pages');
  // there are 200 block types; listing them all would bury the modules, so the sidebar
  // carries the one link and lets `blocks.html` do the listing
  var onBlock = (W.blocks || []).some(function (b) { return b.n === active; });
  W.pages.forEach(function (p) {
    var here = active === p[0].replace('.html', '') || (onBlock && p[0] === 'blocks.html');
    var a = el('a', here ? 'on' : '', p[1]);
    a.href = base + p[0];
    pages.appendChild(a);
  });
  nav.appendChild(pages);

  function navGroup(label, entries, dir) {
    if (!entries.length) return;
    var d = el('details', 'group');
    d.appendChild(el('summary', null, label + ' (' + entries.length + ')'));
    entries.forEach(function (e) {
      var a = el('a', e.n === active ? 'on' : '', e.n);
      a.href = base + dir + '/' + e.n.replace(/[^A-Za-z0-9_-]/g, '-') + '.html';
      d.appendChild(a);
      if (e.n === active) d.open = true;
    });
    nav.appendChild(d);
  }

  var byGroup = {};
  W.modules.forEach(function (m) { (byGroup[m.c] = byGroup[m.c] || []).push(m); });
  W.groups.forEach(function (g) { navGroup(g, byGroup[g] || [], 'm'); });

  // search over module names, field names, types and enums
  var q = document.getElementById('q'), out = document.getElementById('results');
  function slug(s) { return s.replace(/[^A-Za-z0-9_-]/g, '-'); }
  function modHref(mod, field) {
    return 'm/' + slug(mod) + '.html' + (field ? '#' + slug(field) : '');
  }
  var index = [], byField = {};
  function own(entry, dir, name) {
    // a keyword that several blocks declare is one result carrying all of them
    entry.f.forEach(function (f) {
      if (!byField[f]) { byField[f] = { k: f, t: 'field', mods: [] }; index.push(byField[f]); }
      byField[f].mods.push({ n: name, d: dir });
    });
  }
  W.modules.forEach(function (m) {
    index.push({ k: m.n, t: 'module', h: modHref(m.n), s: m.c });
    own(m, 'm', m.n);
  });
  (W.blocks || []).forEach(function (b) {
    index.push({ k: b.n, t: 'block', h: 'b/' + slug(b.n) + '.html', s: 'INI block' });
    own(b, 'b', b.n);
  });
  Object.keys(byField).forEach(function (f) {
    var e = byField[f];
    e.s = e.mods.length === 1 ? e.mods[0].n : e.mods.length + ' blocks';
    if (e.mods.length === 1) e.h = e.mods[0].d + '/' + slug(e.mods[0].n) + '.html#' + slug(f);
  });
  W.types.forEach(function (t) {
    index.push({
      k: t[0], t: 'type', s: t[1].toLowerCase(),
      h: 'types.html#' + t[0].replace(/[^A-Za-z0-9_-]/g, '-')
    });
  });
  W.enums.forEach(function (e) {
    index.push({ k: e, t: 'enum', s: 'enumeration', h: 'enums.html#' + e.replace(/[^A-Za-z0-9_-]/g, '-') });
  });

  var rank = { module: 0, block: 1, type: 2, enum: 3, field: 4 };
  function search(term) {
    var needle = term.toLowerCase(), hits = [];
    for (var i = 0; i < index.length && hits.length < 400; i++) {
      var pos = index[i].k.toLowerCase().indexOf(needle);
      if (pos >= 0) hits.push({ e: index[i], p: pos });
    }
    hits.sort(function (a, b) {
      return (a.p - b.p) || (rank[a.e.t] - rank[b.e.t]) ||
             (a.e.k.length - b.e.k.length) || a.e.k.localeCompare(b.e.k);
    });
    return hits.slice(0, 40);
  }

  var cursor = -1;
  function render(hits) {
    out.innerHTML = '';
    cursor = -1;
    if (!hits.length) {
      out.appendChild(el('div', 'empty', 'No match'));
    }
    hits.forEach(function (h) {
      var e = h.e;
      if (e.t === 'field' && !e.h) {
        var d = el('details', 'hit group');
        var sum = el('summary');
        sum.appendChild(el('b', null, e.k));
        sum.appendChild(el('span', null, 'field - ' + e.s));
        d.appendChild(sum);
        e.mods.forEach(function (mod) {
          var link = el('a', 'sub', mod.n);
          link.href = base + mod.d + '/' + slug(mod.n) + '.html#' + slug(e.k);
          d.appendChild(link);
        });
        out.appendChild(d);
        return;
      }
      var a = el('a', 'hit');
      a.href = base + e.h;
      a.appendChild(el('b', null, e.k));
      a.appendChild(el('span', null, e.t + ' - ' + e.s));
      out.appendChild(a);
    });
    out.hidden = false;
    nav.hidden = true;
  }
  function clear() { out.hidden = true; out.innerHTML = ''; nav.hidden = false; cursor = -1; }

  q.addEventListener('input', function () {
    var v = q.value.trim();
    if (v.length < 2) { clear(); return; }
    render(search(v));
  });
  q.addEventListener('keydown', function (e) {
    var hits = out.querySelectorAll('.hit');
    if (e.key === 'Escape') { q.value = ''; clear(); q.blur(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!hits.length) return;
      e.preventDefault();
      if (cursor >= 0) hits[cursor].classList.remove('on');
      cursor = (cursor + (e.key === 'ArrowDown' ? 1 : hits.length - 1)) % hits.length;
      hits[cursor].classList.add('on');
      hits[cursor].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && cursor >= 0) {
      var hit = hits[cursor];
      if (hit.tagName === 'DETAILS') hit.open = !hit.open; else hit.click();
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); }
  });

  // typed-in values: checked against the field's type, then written into the INI block
  var iniCode = document.getElementById('ini');
  var fieldTable = document.querySelector('table.fields[data-module]');
  var NUM = /^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$/;
  var RANGES = { int8: [-128, 127], uint8: [0, 255], uint16: [0, 65535] };
  var PARTS = { coord3: ['X', 'Y', 'Z'], rgb: ['R', 'G', 'B'], rgba: ['R', 'G', 'B', 'A'] };

  function memberOf(list, token) {
    var t = token.replace(/^[+-]/, '').toUpperCase();
    if (t === 'ALL' || t === 'NONE') return true;
    for (var i = 0; i < list.length; i++) if (list[i].toUpperCase() === t) return true;
    return false;
  }

  function complain(value, kind, enumName) {
    var toks = value.split(/\s+/), list = enumName ? (W.members || {})[enumName] : null;
    if (value.charAt(0) === '#') return '';   // an INI macro, resolved at load time
    switch (kind) {
      case 'bool':
        return /^(yes|no)$/i.test(value) ? '' : 'expected Yes or No';
      case 'int': case 'int8': case 'uint8': case 'uint16':
        if (!/^[+-]?\d+$/.test(value)) return 'expected a whole number';
        var lim = RANGES[kind], n = parseInt(value, 10);
        if (lim && (n < lim[0] || n > lim[1])) return 'expected ' + lim[0] + ' to ' + lim[1];
        return '';
      case 'real': case 'positive': case 'nonneg': case 'nonpos':
        if (!NUM.test(value)) return 'expected a number';
        var f = parseFloat(value);
        if (kind === 'positive' && !(f > 0)) return 'expected a number above 0';
        if (kind === 'nonneg' && f < 0) return 'expected 0 or more';
        if (kind === 'nonpos' && f > 0) return 'expected 0 or less';
        return '';
      case 'intrange':
        if (toks.length !== 2 || !/^[+-]?\d+$/.test(toks[0]) || !/^[+-]?\d+$/.test(toks[1]))
          return 'expected two whole numbers';
        return '';
      case 'coord3': case 'rgb': case 'rgba':
        var keys = PARTS[kind];
        for (var j = 0; j < toks.length; j++) {
          var m = /^([A-Za-z]+):(.*)$/.exec(toks[j]);
          if (!m || keys.indexOf(m[1].toUpperCase()) < 0 || !NUM.test(m[2]))
            return 'expected ' + keys.map(function (k) { return k + ':<number>'; }).join(' ');
        }
        return '';
      case 'enum':
        if (toks.length !== 1) return 'expected a single token';
        return (list && !memberOf(list, toks[0])) ? toks[0] + ' is not in ' + enumName : '';
      case 'flags':
        if (!list) return '';
        for (var k = 0; k < toks.length; k++)
          if (!memberOf(list, toks[k])) return toks[k] + ' is not in ' + enumName;
        return '';
      case 'pair':
        if (toks.length !== 2) return 'expected exactly two tokens';
        if (list) for (var q = 0; q < 2; q++)
          if (!memberOf(list, toks[q])) return toks[q] + ' is not in ' + enumName;
        return '';
      case 'keyed':
        if (toks.length < 2) return 'expected a moment, then a name';
        return (list && !memberOf(list, toks[0])) ? toks[0] + ' is not in ' + enumName : '';
      case 'module':
        var known = window.WIKI_FIELDS;
        if (known && known.modules.indexOf(toks[0]) < 0)
          return toks[0] + ' is not a module the engine registers';
        return toks.length < 2 ? 'expected a module, then a tag' : '';
      default:
        return '';
    }
  }

  function fillPickers() {
    var picks = document.querySelectorAll('select.fieldval[data-members]');
    for (var i = 0; i < picks.length; i++) {
      var pick = picks[i], list = (W.members || {})[pick.getAttribute('data-members')] || [];
      for (var j = 0; j < list.length; j++) {
        var opt = document.createElement('option');
        opt.textContent = list[j];
        pick.appendChild(opt);
      }
    }
  }

  function controlValue(control) {
    if (control.tagName !== 'SELECT') return control.value.trim();
    if (!control.multiple) return control.value.trim();
    var sign = control.getAttribute('data-sign') || '', picked = [];
    for (var i = 0; i < control.options.length; i++)
      if (control.options[i].selected) picked.push(sign + control.options[i].value);
    return picked.join(' ');
  }

  function rebuildIni() {
    var inputs = fieldTable.querySelectorAll('.fieldval');
    var written = [], width = 0, i;
    for (i = 0; i < inputs.length; i++) {
      var inp = inputs[i], typed = controlValue(inp);
      var value = typed || inp.getAttribute('data-default') || '';
      // a keyword with neither a typed value nor a default is not a line you could paste
      if (!value) continue;
      var name = inp.getAttribute('data-field');
      written.push({ name: name, value: value, typed: !!typed });
      if (name.length > width) width = name.length;
    }
    iniCode.textContent = '';
    var head = document.createElement('span');
    head.textContent = fieldTable.getAttribute('data-module') + ' ModuleTag_01\n';
    iniCode.appendChild(head);
    written.forEach(function (line) {
      var pad = line.name;
      while (pad.length < width) pad += ' ';
      var span = document.createElement('span');
      if (line.typed) span.className = 'set';
      span.textContent = '  ' + pad + ' = ' + line.value + '\n';
      iniCode.appendChild(span);
    });
    iniCode.appendChild(document.createTextNode('End'));
  }

  if (fieldTable && iniCode) {
    fillPickers();
    fieldTable.addEventListener('change', onValue);
    fieldTable.addEventListener('input', onValue);
  }

  function onValue(e) {
      var inp = e.target;
      if (!inp.classList || !inp.classList.contains('fieldval')) return;
      var value = controlValue(inp);
      var why = value ? complain(value, inp.getAttribute('data-kind'),
                                 inp.getAttribute('data-enum')) : '';
      inp.classList.toggle('bad', !!why);
      inp.setAttribute('aria-invalid', why ? 'true' : 'false');
      if (why) inp.title = why; else inp.removeAttribute('title');
      var note = inp.parentNode.querySelector('.why');
      if (note) note.textContent = why;
      rebuildIni();
  }

  // paste a block, check every keyword in it against the engine's field tables
  var checkInput = document.getElementById('checkinput');

  function stripComment(line) {
    var out = '', quoted = false;
    for (var i = 0; i < line.length; i++) {
      var c = line.charAt(i);
      if (c === '"') quoted = !quoted;
      if (!quoted && (c === ';' || (c === '/' && line.charAt(i + 1) === '/'))) break;
      out += c;
    }
    return out;
  }

  function schemaFor(name) {
    var F = window.WIKI_FIELDS;
    return (F && F.schemas[name]) || null;
  }

  function isModule(name) {
    var F = window.WIKI_FIELDS;
    return !!(F && F.modules.indexOf(name) >= 0);
  }

  function isBlockType(name) {
    var F = window.WIKI_FIELDS;
    return !!(F && F.blocks.indexOf(name) >= 0);
  }

  function checkText(text) {
    var lines = text.split(/\r?\n/), stack = [], report = [], seen = [];
    var totals = { keywords: 0, errors: 0, redundant: 0, blocks: 0 };

    function top() { return stack.length ? stack[stack.length - 1] : null; }

    for (var n = 0; n < lines.length; n++) {
      var raw = lines[n], line = stripComment(raw).trim();
      var row = { no: n + 1, text: raw, state: 'plain', note: '' };
      if (!line) { report.push(row); continue; }

      if (/^end$/i.test(line)) {
        if (!stack.length) {
          row.state = 'error';
          row.note = 'End without a block to close';
          totals.errors++;
        } else {
          var done = stack.pop();
          row.state = 'block';
          row.note = 'closes ' + (done.name || 'the block');
        }
        report.push(row);
        continue;
      }

      var eq = line.indexOf('='), key, value;
      if (eq >= 0) {
        key = line.slice(0, eq).trim();
        value = line.slice(eq + 1).trim();
      } else {
        var words = line.split(/\s+/);
        key = words[0];
        value = words.slice(1).join(' ');   // `Object GondorSoldier` names the block
      }
      var first = value.split(/\s+/)[0] || '';
      var scope = top();
      var schema = scope && scope.name ? schemaFor(scope.name) : null;
      var spec = schema ? schema[key] : null;

      // what the keyword does comes from the schema it sits in: a `Module` keyword
      // attaches the module its value names, a keyword typed as a block opens that
      // block, and a keyword with no value that names a block is a header
      var opened = null, unknownModule = false;
      if (spec && spec[0] === 'module') {
        opened = schemaFor(first) ? first : null;
        unknownModule = !opened;
      } else if (spec && schemaFor(spec[3])) {
        opened = spec[3];
      } else if (!spec && isModule(first)) {
        opened = first;
      } else if (schemaFor(key) && (!spec || !value)) {
        opened = key;
      } else if (eq < 0 && scope) {
        // a keyword on a line of its own opens something; without a schema for it the
        // honest thing is to skip its contents rather than judge them
        unknownModule = true;
      }

      if (opened) {
        stack.push({ name: opened, line: n + 1, set: {} });
        seen.push(stack[stack.length - 1]);
        totals.blocks++;
        if (spec) scope.set[key] = true;
        row.state = 'block';
        row.note = 'opens ' + opened;
        report.push(row);
        continue;
      }
      if (unknownModule) {
        stack.push({ name: null, line: n + 1, set: {} });
        row.state = 'warn';
        row.note = (spec && spec[0] === 'module' ? first : key) +
                   ' opens a block with no schema here, so its contents are not checked';
        report.push(row);
        continue;
      }

      if (!scope) {
        row.state = 'warn';
        row.note = 'outside any block';
        report.push(row);
        continue;
      }
      if (!scope.name) { report.push(row); continue; }

      totals.keywords++;
      if (!spec) {
        row.state = 'error';
        row.note = key + ' is not a keyword of ' + scope.name;
        totals.errors++;
        report.push(row);
        continue;
      }
      scope.set[key] = true;
      var why = value ? complain(value, spec[0], spec[1]) : '';
      if (why) {
        row.state = 'error';
        row.note = why;
        totals.errors++;
      } else if (spec[2] !== null && spec[2] !== undefined && value === String(spec[2])) {
        row.state = 'warn';
        row.note = 'same as the default, so the line does nothing';
        totals.redundant++;
      } else {
        row.state = 'ok';
        row.note = spec[4] ? 'names a ' + spec[4] : spec[3];
      }
      report.push(row);
    }

    stack.forEach(function (open) {
      totals.errors++;
      report.push({ no: lines.length, text: '', state: 'error',
                    note: (open.name || 'block') + ' opened on line ' + open.line +
                          ' is never closed' });
    });
    return { report: report, totals: totals, seen: seen };
  }

  function renderCheck(result) {
    var out = document.getElementById('checkout');
    out.innerHTML = '';
    var table = el('table', 'checktable');
    var body = document.createElement('tbody');
    result.report.forEach(function (row) {
      var tr = document.createElement('tr');
      tr.className = row.state;
      var no = el('td', 'lineno', String(row.no));
      var text = el('td', 'linetext', row.text);
      var note = el('td', 'linenote', row.note);
      tr.appendChild(no);
      tr.appendChild(text);
      tr.appendChild(note);
      body.appendChild(tr);
    });
    table.appendChild(body);
    out.appendChild(table);

    result.seen.forEach(function (scope) {
      var schema = schemaFor(scope.name);
      if (!schema) return;
      var missing = Object.keys(schema).filter(function (k) {
        return !scope.set[k] && schema[k][2] !== null && schema[k][2] !== undefined;
      });
      if (!missing.length) return;
      var d = el('details', 'defaults');
      d.appendChild(el('summary', null,
        scope.name + ': ' + missing.length + ' keyword' + (missing.length === 1 ? '' : 's') +
        ' you did not set, and what they default to'));
      var pre = document.createElement('pre');
      var width = 0;
      missing.forEach(function (k) { if (k.length > width) width = k.length; });
      pre.textContent = missing.map(function (k) {
        var pad = k;
        while (pad.length < width) pad += ' ';
        return '  ' + pad + ' = ' + schema[k][2];
      }).join('\n');
      d.appendChild(pre);
      out.appendChild(d);
    });

    var t = result.totals;
    var summary = document.getElementById('checksummary');
    summary.className = t.errors ? 'bad' : 'good';
    summary.textContent = t.keywords + ' keyword' + (t.keywords === 1 ? '' : 's') +
      ' in ' + t.blocks + ' block' + (t.blocks === 1 ? '' : 's') + ' - ' +
      t.errors + ' problem' + (t.errors === 1 ? '' : 's') + ', ' +
      t.redundant + ' line' + (t.redundant === 1 ? '' : 's') + ' equal to the default';
  }

  if (checkInput) {
    var run = function () { renderCheck(checkText(checkInput.value)); };
    document.getElementById('checkrun').addEventListener('click', run);
    document.getElementById('checkclear').addEventListener('click', function () {
      checkInput.value = '';
      document.getElementById('checkout').innerHTML = '';
      document.getElementById('checksummary').textContent = '';
    });
    var pending = null;
    checkInput.addEventListener('input', function () {
      clearTimeout(pending);
      pending = setTimeout(run, 350);
    });
  }

  var copyBtn = document.querySelector('.copyini');
  if (copyBtn && iniCode) {
    copyBtn.addEventListener('click', function () {
      var text = iniCode.textContent;
      function done() {
        var was = copyBtn.textContent;
        copyBtn.textContent = 'Copied';
        setTimeout(function () { copyBtn.textContent = was; }, 1400);
      }
      function fallback() {
        var ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); } catch (err) { /* nothing to do */ }
        document.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, fallback);
      } else {
        fallback();
      }
    });
  }

  // column sort
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var dir = {};
    table.querySelectorAll('th').forEach(function (th, col) {
      th.addEventListener('click', function () {
        var rows = Array.prototype.slice.call(table.tBodies[0].rows);
        dir[col] = !dir[col];
        rows.sort(function (a, b) {
          var x = a.cells[col].textContent.trim(), y = b.cells[col].textContent.trim();
          var nx = parseFloat(x), ny = parseFloat(y);
          var c = (!isNaN(nx) && !isNaN(ny) && x !== '' && y !== '')
                  ? nx - ny : x.localeCompare(y);
          return dir[col] ? c : -c;
        });
        rows.forEach(function (r) { table.tBodies[0].appendChild(r); });
      });
    });
  });

  var menu = document.getElementById('menu');
  if (menu) menu.addEventListener('click', function () { body.classList.toggle('nav-open'); });
})();
