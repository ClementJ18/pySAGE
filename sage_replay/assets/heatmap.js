(function () {
  var STEPS = [15, 30, 60, 120, 300, 600, 1200];

  function clock(seconds) {
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  // Unlike the timeline's escaper this one also covers `"`: heatmap labels land in a
  // title attribute as well as element text.
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }

  function binning(payload, mode) {
    if (mode === 'pct') return { bins: 20, size: 5, pct: true };
    var max = 0;
    payload.series.forEach(function (s) {
      s.occ.forEach(function (p) { if (p[1] > max) max = p[1]; });
    });
    if (!max) max = 60;
    var size = STEPS[STEPS.length - 1];
    for (var i = 0; i < STEPS.length; i++) {
      if (Math.ceil(max / STEPS[i]) <= 24) { size = STEPS[i]; break; }
    }
    return { bins: Math.max(1, Math.ceil(max / size)), size: size, pct: false };
  }

  function counts(s, spec) {
    var out = [], b;
    for (b = 0; b < spec.bins; b++) out.push(0);
    s.occ.forEach(function (p) {
      if (spec.pct) b = Math.floor(p[0] / p[1] * spec.bins);
      else b = Math.floor(p[0] / spec.size);
      out[Math.max(0, Math.min(spec.bins - 1, b))] += 1;
    });
    return out;
  }

  // The centred 3-bin moving average the shading reads; an edge bin averages over the
  // neighbours it has. Mirrors `_GRAPH_SCRIPT`'s smoother exactly.
  function smooth(raw) {
    return raw.map(function (c, b) {
      var sum = c, n = 1;
      if (b > 0) { sum += raw[b - 1]; n += 1; }
      if (b + 1 < raw.length) { sum += raw[b + 1]; n += 1; }
      return sum / n;
    });
  }

  function axisTicks(spec) {
    var ticks = [];
    if (spec.pct) {
      [0, 25, 50, 75, 100].forEach(function (t) { ticks.push({ at: t, label: t + '%' }); });
    } else {
      var span = spec.bins * spec.size;
      var step = spec.size * Math.max(1, Math.ceil(spec.bins / 6));
      for (var t = 0; t <= span; t += step) {
        ticks.push({ at: t / span * 100, label: clock(t) });
      }
    }
    return ticks.map(function (tick) {
      // Anchor by the tick's value, not its index: in abs mode the tick step need not
      // divide the span, so the last tick can sit short of the right edge and must keep
      // its true position rather than be pinned to 100%.
      var style = tick.at <= 0 ? 'left:0'
        : tick.at >= 100 ? 'left:100%;transform:translateX(-100%)'
        : 'left:' + tick.at + '%;transform:translateX(-50%)';
      return '<span style="' + style + '">' + tick.label + '</span>';
    }).join('');
  }

  Array.prototype.forEach.call(document.querySelectorAll('details.heatmap'), function (details) {
    var payload = JSON.parse(details.querySelector('script.hm-data').textContent);
    var grid = details.querySelector('.hm-grid');
    var wrap = details.querySelector('.hm-wrap');
    var tip = details.querySelector('.tl-tip');
    var mode = 'pct';
    var rendered = false;
    var view = null;

    function render() {
      rendered = true;
      var spec = binning(payload, mode);
      var series = payload.series.map(function (s) {
        var raw = counts(s, spec);
        var sm = smooth(raw);
        var maxSm = 0;
        sm.forEach(function (v) { if (v > maxSm) maxSm = v; });
        return { label: s.label, n: s.occ.length, raw: raw, sm: sm, maxSm: maxSm };
      });
      var rows = series.map(function (s, i) {
        var cells = '';
        for (var b = 0; b < spec.bins; b++) {
          // Smoothing drives intensity only; a bin with no actual purchases stays
          // uncoloured rather than inheriting spillover from its neighbours (the
          // tooltip reports raw counts, so a tinted "0 of n" cell would lie).
          var style = '';
          if (s.raw[b] > 0) {
            var pct = 10 + (s.sm[b] / s.maxSm) * 75;
            style = ' style="background: color-mix(in srgb, var(--above) ' +
              pct.toFixed(1) + '%, transparent)"';
          }
          cells += '<span class="hm-cell" data-i="' + i + '" data-b="' + b + '"' + style + '></span>';
        }
        return '<div class="hm-row"><div class="hm-label" title="' + esc(s.label) + '">' +
          esc(s.label) + '<span class="n">' + s.n + '</span></div>' +
          '<div class="hm-cells">' + cells + '</div></div>';
      }).join('');
      grid.innerHTML = rows + '<div class="hm-axis">' + axisTicks(spec) + '</div>';
      view = { spec: spec, series: series };
    }

    Array.prototype.forEach.call(details.querySelectorAll('.tl-toggle button'), function (btn) {
      btn.addEventListener('click', function () {
        if (btn.dataset.mode === mode) return;
        mode = btn.dataset.mode;
        Array.prototype.forEach.call(details.querySelectorAll('.tl-toggle button'), function (o) {
          o.classList.toggle('on', o === btn);
        });
        render();
      });
    });

    details.addEventListener('toggle', function () {
      if (details.open && !rendered) render();
    });
    if (details.open) render();

    wrap.addEventListener('mouseover', function (e) {
      var cell = e.target;
      if (!cell.classList || !cell.classList.contains('hm-cell') || !view) { return; }
      var s = view.series[+cell.dataset.i];
      var b = +cell.dataset.b;
      if (!s || !(s.raw[b] > 0)) { tip.hidden = true; return; }
      var size = view.spec.size;
      var range = view.spec.pct
        ? (b * size) + '\u2013' + ((b + 1) * size) + '% of match'
        : clock(b * size) + '\u2013' + clock((b + 1) * size);
      tip.innerHTML = '<b>' + esc(s.label) + '</b> ' + s.raw[b] + ' of ' + s.n +
        ' purchases \u00b7 ' + range;
      tip.hidden = false;
      var rect = wrap.getBoundingClientRect();
      var cr = cell.getBoundingClientRect();
      var left = cr.left - rect.left + cr.width / 2 + 8;
      if (left + tip.offsetWidth > rect.width - 4) left -= tip.offsetWidth + cr.width + 16;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, cr.top - rect.top - 30) + 'px';
    });
    wrap.addEventListener('mouseleave', function () {
      tip.hidden = true;
    });
  });
})();
