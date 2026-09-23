(function () {
  var W = 720, H = 240;
  var PAD = { l: 46, r: 14, t: 10, b: 28 };
  var STEPS = [15, 30, 60, 120, 300, 600, 1200];
  var NOTES = {
    share: 'share of visible series\' orders per bin',
    cpshare: 'share of visible series\' command points per bin',
    lifecycle: '% of the unit\'s own orders per bin',
    count: 'total orders per bin',
    cumulative: 'cumulative % of the unit\'s orders'
  };

  function clock(seconds) {
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  function fmt(v) { return v ? parseFloat(v.toPrecision(3)).toString() : '0'; }
  function asPct(v) { return fmt(v * 100) + '%'; }
  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function slot(i) { return 'var(--s' + ((i % 8) + 1) + ')'; }
  function niceStep(raw) {
    var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
    var norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  }
  function total(arr) {
    var t = 0;
    arr.forEach(function (v) { t += v; });
    return t;
  }

  Array.prototype.forEach.call(document.querySelectorAll('details.timeline'), function (details) {
    var id = details.dataset.graph;
    var payload = JSON.parse(details.querySelector('script.tl-data').textContent);
    var wrap = details.querySelector('.tl-wrap');
    var tip = details.querySelector('.tl-tip');
    var note = details.querySelector('.tl-note');
    var boxes = document.querySelectorAll('input[data-graph="' + id + '"]');
    var master = document.querySelector('input[data-graph-all="' + id + '"]');
    var mode = 'pct';
    var ymode = 'share';
    var rendered = false;
    var view = null;

    function syncMaster() {
      if (!master) return;
      var on = 0;
      Array.prototype.forEach.call(boxes, function (box) { if (box.checked) on++; });
      master.checked = on === boxes.length;
      master.indeterminate = on > 0 && on < boxes.length;
    }

    Array.prototype.forEach.call(boxes, function (box) {
      var i = +box.dataset.series;
      var swatch = box.nextElementSibling;
      if (swatch) {
        swatch.style.setProperty('--c', slot(i));
        if (i >= 8) swatch.classList.add('dashed');
      }
      box.addEventListener('change', function () { syncMaster(); if (rendered) render(); });
    });

    if (master) {
      // The select-all lives inside a sortable column header: swallow the click so ticking
      // it never also re-sorts the table.
      master.addEventListener('click', function (e) { e.stopPropagation(); });
      master.addEventListener('change', function () {
        Array.prototype.forEach.call(boxes, function (box) { box.checked = master.checked; });
        if (rendered) render();
      });
    }

    function binning() {
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

    // The centred 3-bin moving average the derived modes read; an edge bin averages over
    // the neighbours it has.
    function smooth(raw) {
      return raw.map(function (c, b) {
        var sum = c, n = 1;
        if (b > 0) { sum += raw[b - 1]; n += 1; }
        if (b + 1 < raw.length) { sum += raw[b + 1]; n += 1; }
        return sum / n;
      });
    }

    function render() {
      rendered = true;
      var spec = binning();
      var series = [];
      Array.prototype.forEach.call(boxes, function (box) {
        var i = +box.dataset.series;
        if (box.checked && payload.series[i]) {
          var raw = counts(payload.series[i], spec);
          series.push({ i: i, label: payload.series[i].label, raw: raw, sm: smooth(raw) });
        }
      });
      // Derive what each visible series plots in the current y-mode. share, lifecycle
      // and count read the smoothed counts; cumulative runs over the raw counts, which is
      // already noise-proof and must stay monotonic. A null value is a gap the path breaks
      // over: a share where no visible series bought anything, or a series with no orders
      // at all - never a fabricated 0.
      if (ymode === 'share' || ymode === 'cpshare') {
        // cpshare is share with each series' smoothed counts scaled by its CommandPoints
        // weight (cp, shipped per series only when the renderer had a `weight` hook). A
        // 0-CP series contributes nothing to the denominator and draws along zero; a bin
        // where every visible series weighs out entirely gaps like an empty share bin.
        var denom = [];
        series.forEach(function (l) {
          l.w = ymode === 'cpshare' ? (payload.series[l.i].cp || 0) : 1;
          l.sm.forEach(function (v, b) { denom[b] = (denom[b] || 0) + v * l.w; });
        });
        series.forEach(function (l) {
          l.vals = l.sm.map(function (v, b) {
            return denom[b] > 0 ? v * l.w / denom[b] : null;
          });
        });
      } else if (ymode === 'lifecycle') {
        series.forEach(function (l) {
          var t = total(l.sm);
          l.vals = l.sm.map(function (v) { return t > 0 ? v / t : null; });
        });
      } else if (ymode === 'count') {
        series.forEach(function (l) { l.vals = l.sm; });
      } else {
        series.forEach(function (l) {
          var t = total(l.raw), run = 0;
          l.vals = l.raw.map(function (c) { run += c; return t > 0 ? run / t : null; });
        });
      }
      var pctY = ymode !== 'count';
      var ymax = 0;
      series.forEach(function (l) {
        l.vals.forEach(function (v) { if (v !== null && v > ymax) ymax = v; });
      });
      if (!ymax) ymax = 1;
      var step = niceStep(ymax / 4);
      var top = Math.ceil(ymax / step - 1e-9) * step;
      var pw = W - PAD.l - PAD.r, ph = H - PAD.t - PAD.b;
      function x(b) { return PAD.l + (b + 0.5) / spec.bins * pw; }
      function y(v) { return PAD.t + ph - v / top * ph; }
      var svg = [], k, t, tx;
      for (k = 0; k * step <= top + step / 2; k++) {
        var gy = y(k * step);
        svg.push('<line class="grid" x1="' + PAD.l + '" x2="' + (W - PAD.r) +
          '" y1="' + gy.toFixed(1) + '" y2="' + gy.toFixed(1) + '"/>');
        svg.push('<text x="' + (PAD.l - 6) + '" y="' + (gy + 3).toFixed(1) +
          '" text-anchor="end">' + (pctY ? asPct(k * step) : fmt(k * step)) + '</text>');
      }
      if (spec.pct) {
        for (t = 0; t <= 100; t += 25) {
          tx = PAD.l + t / 100 * pw;
          svg.push('<text x="' + tx.toFixed(1) + '" y="' + (H - PAD.b + 15) +
            '" text-anchor="middle">' + t + '%</text>');
        }
      } else {
        var span = spec.bins * spec.size;
        var tickStep = spec.size * Math.max(1, Math.ceil(spec.bins / 6));
        for (t = 0; t <= span; t += tickStep) {
          tx = PAD.l + t / span * pw;
          svg.push('<text x="' + tx.toFixed(1) + '" y="' + (H - PAD.b + 15) +
            '" text-anchor="middle">' + clock(t) + '</text>');
        }
      }
      series.forEach(function (l) {
        var d = '', pen = false;
        l.vals.forEach(function (v, b) {
          if (v === null) { pen = false; return; }
          d += (pen ? 'L' : 'M') + x(b).toFixed(1) + ' ' + y(v).toFixed(1);
          pen = true;
        });
        if (!d) return;
        svg.push('<path class="series" style="stroke: ' + slot(l.i) + '"' +
          (l.i >= 8 ? ' stroke-dasharray="5 4"' : '') + ' d="' + d + '"/>');
      });
      svg.push('<line class="tl-cross" y1="' + PAD.t + '" y2="' + (H - PAD.b) +
        '" style="display:none"/>');
      svg.push('<circle class="tl-dot" r="3.5" style="display:none"/>');
      details.querySelector('.tl-svg').innerHTML =
        '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + svg.join('') + '</svg>';
      view = { spec: spec, series: series, x: x, y: y };
    }

    // Each pill toggle is its own group: the x-axis buttons carry data-mode, the y-mode
    // buttons data-ymode, and a click only repaints the on-state within its own group.
    Array.prototype.forEach.call(details.querySelectorAll('.tl-toggle'), function (group) {
      var buttons = group.querySelectorAll('button');
      Array.prototype.forEach.call(buttons, function (btn) {
        btn.addEventListener('click', function () {
          var isY = !btn.dataset.mode;
          var next = isY ? btn.dataset.ymode : btn.dataset.mode;
          if (next === (isY ? ymode : mode)) return;
          if (isY) { ymode = next; note.textContent = NOTES[ymode]; }
          else mode = next;
          Array.prototype.forEach.call(buttons, function (o) {
            o.classList.toggle('on', o === btn);
          });
          render();
        });
      });
    });

    details.addEventListener('toggle', function () {
      if (details.open && !rendered) render();
    });
    if (details.open) render();

    wrap.addEventListener('mousemove', function (e) {
      var svgEl = wrap.querySelector('svg');
      if (!view || !view.series.length || !svgEl) return;
      var rect = svgEl.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      var mx = (e.clientX - rect.left) / rect.width * W;
      var my = (e.clientY - rect.top) / rect.height * H;
      var b = Math.round((mx - PAD.l) / (W - PAD.l - PAD.r) * view.spec.bins - 0.5);
      b = Math.max(0, Math.min(view.spec.bins - 1, b));
      var best = null, dist = Infinity;
      view.series.forEach(function (l) {
        if (l.vals[b] === null) return;  // a gap bin has no point to read out
        var d = Math.abs(view.y(l.vals[b]) - my);
        if (d < dist) { dist = d; best = l; }
      });
      var cross = svgEl.querySelector('.tl-cross'), dot = svgEl.querySelector('.tl-dot');
      if (!best) {  // every visible series gaps here - nothing to point at
        tip.hidden = true;
        cross.style.display = 'none';
        dot.style.display = 'none';
        return;
      }
      var cx = view.x(b), cy = view.y(best.vals[b]);
      cross.setAttribute('x1', cx); cross.setAttribute('x2', cx);
      cross.style.display = '';
      dot.setAttribute('cx', cx); dot.setAttribute('cy', cy);
      dot.style.fill = slot(best.i);
      dot.style.display = '';
      var size = view.spec.size;
      var range = view.spec.pct
        ? b * size + '\u2013' + (b + 1) * size + '% of match'
        : clock(b * size) + '\u2013' + clock((b + 1) * size);
      var v = best.vals[b], text;
      if (ymode === 'share') {
        text = asPct(v) + ' of buys &middot; ' + range + ' (n=' + best.raw[b] + ')';
      } else if (ymode === 'cpshare') {
        text = asPct(v) + ' of CP spent &middot; ' + range + ' (n=' + best.raw[b] + ')';
      } else if (ymode === 'lifecycle') {
        text = asPct(v) + ' of its orders &middot; ' + range;
      } else if (ymode === 'count') {
        text = best.raw[b] + (best.raw[b] === 1 ? ' order' : ' orders') + ' &middot; ' + range;
      } else {
        text = asPct(v) + ' by ' +
          (view.spec.pct ? (b + 1) * size + '% of match' : clock((b + 1) * size));
      }
      tip.innerHTML = '<b>' + esc(best.label) + '</b> ' + text;
      tip.hidden = false;
      var left = cx / W * rect.width + 12;
      if (left + tip.offsetWidth > rect.width - 4) left -= tip.offsetWidth + 24;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, cy / H * rect.height - 30) + 'px';
    });
    wrap.addEventListener('mouseleave', function () {
      tip.hidden = true;
      var svgEl = wrap.querySelector('svg');
      if (!svgEl) return;
      svgEl.querySelector('.tl-cross').style.display = 'none';
      svgEl.querySelector('.tl-dot').style.display = 'none';
    });
  });
})();
