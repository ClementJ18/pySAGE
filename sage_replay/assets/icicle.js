(function () {
  var CAT = { buildings: '--s1', units: '--s2', heroes: '--s3' };
  var W = 720, H = 300, PAD = 3, GAP = 2, MIN_LABEL = 11, CHAR = 5.4;

  function clock(seconds) {
    if (seconds === null || seconds === undefined) return '-';
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  }
  // The by-step science annotation as the readout's trailing list, already clock-sorted
  // server-side: 'label m:ss (NN%)' per entry, share = that science's games over the node's own
  // games, or 'none yet' when the node carries no science annotation at all.
  function sciText(n) {
    if (!n.sciences.length) return 'none yet';
    var parts = [];
    n.sciences.forEach(function (s) {
      var pct = n.games > 0 ? Math.round(s.games / n.games * 100) : 0;
      parts.push(esc(s.label) + ' ' + clock(s.median_seconds) + ' (' + pct + '%)');
    });
    return parts.join(' \u00b7 ');
  }
  function maxDepth(node, d) {
    var m = d;
    (node.children || []).forEach(function (c) {
      var cd = maxDepth(c, d + 1);
      if (cd > m) m = cd;
    });
    return m;
  }

  Array.prototype.forEach.call(document.querySelectorAll('.bo-ice-wrap'), function (wrap) {
    var root = JSON.parse(wrap.querySelector('script.ice-data').textContent);
    var host = wrap.querySelector('.bo-ice');
    var tip = wrap.querySelector('.tl-tip');
    var sciBox = wrap.querySelector('.ice-sci');
    var defaultSci = sciBox ? sciBox.textContent : '';
    var diff = !!root.diff;
    var nodes = [];
    var rendered = false;
    var pinned = -1;

    function render() {
      if (rendered) return;
      rendered = true;
      var depth = Math.max(1, maxDepth(root, 0));
      var colW = (W - PAD * 2) / depth;
      var svg = [];

      // Partition a parent band [y0, y1] (its games mapping to the whole band) among its children
      // top-aligned, the pruned remainder left blank at the bottom; emit a rect per real node.
      function walk(node, y0, y1, d, parentIdx) {
        var idx = -1;
        if (d >= 1) {
          idx = nodes.length;
          var x = PAD + (d - 1) * colW, w = colW - GAP, h = y1 - y0;
          var fill = CAT[node.category] || '--muted';
          var isNew = diff && (node.base_share === null || node.base_share === undefined);
          svg.push('<rect class="ice-box" data-i="' + idx + '" x="' + x.toFixed(1) +
            '" y="' + y0.toFixed(1) + '" width="' + w.toFixed(1) + '" height="' + h.toFixed(1) +
            '" fill="var(' + fill + ')" stroke="var(--surface)"' +
            (isNew ? ' stroke-dasharray="3 2" style="stroke:var(--ink)"' : '') + '/>');
          nodes.push({ parent: parentIdx, label: node.label, games: node.games,
            parentGames: parentIdx >= 0 ? nodes[parentIdx].games : root.games,
            wins: node.wins, losses: node.losses, ms: node.median_seconds,
            sciences: node.sciences || [],
            base: (node.base_share === undefined ? null : node.base_share) });
          if (h >= MIN_LABEL) {
            var count = (node.median_count && node.median_count > 1)
              ? ' \u00d7' + node.median_count : '';
            var label = node.label + count;
            var fit = Math.floor((w - 6) / CHAR);
            if (label.length > fit) label = fit > 1 ? label.slice(0, fit - 1) + '\u2026' : '';
            if (label) {
              svg.push('<text class="ice-label" x="' + (x + 3).toFixed(1) + '" y="' +
                (y0 + h / 2).toFixed(1) + '" dominant-baseline="middle">' + esc(label) + '</text>');
            }
          }
        }
        var kids = node.children || [];
        if (node.games > 0) {
          var scale = (y1 - y0) / node.games, cursor = y0;
          kids.forEach(function (c) {
            var ch = c.games * scale;
            walk(c, cursor, cursor + ch, d + 1, idx);
            cursor += ch;
          });
        }
      }
      walk(root, PAD, H - PAD, 0, -1);
      host.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img">' + svg.join('') +
        '</svg>';
    }

    function ancestors(i) {
      var set = {};
      while (i >= 0) { set[i] = true; i = nodes[i].parent; }
      return set;
    }

    // The readout box: unpinned, it tracks the hovered node; pinned, it stays on that node (a
    // '(pinned)' suffix and the 'pinned' class marking it) until unpinned again.
    function showSci(i) {
      if (!sciBox) return;
      var n = nodes[i];
      var html = '<b>' + esc(n.label) + '</b> \u00b7 sciences by ~' + clock(n.ms) + ': ' +
        sciText(n);
      if (i === pinned) html += ' (pinned)';
      sciBox.innerHTML = html;
      sciBox.classList.toggle('pinned', i === pinned);
    }
    function resetSci() {
      if (!sciBox) return;
      sciBox.textContent = defaultSci;
      sciBox.classList.remove('pinned');
    }
    function setPin(i) {
      pinned = i;
      Array.prototype.forEach.call(host.querySelectorAll('.ice-box'), function (r) {
        r.classList.remove('ice-pin');
      });
      if (i < 0) { resetSci(); return; }
      var rect = host.querySelector('.ice-box[data-i="' + i + '"]');
      if (rect) rect.classList.add('ice-pin');
      showSci(i);
    }

    host.addEventListener('mouseover', function (e) {
      var rect = e.target;
      if (!rect.classList || !rect.classList.contains('ice-box')) return;
      var i = +rect.getAttribute('data-i');
      var set = ancestors(i);
      Array.prototype.forEach.call(host.querySelectorAll('.ice-box'), function (r) {
        r.style.opacity = set[+r.getAttribute('data-i')] ? '1' : '0.25';
      });
      var n = nodes[i];
      var share = n.parentGames > 0 ? Math.round(n.games / n.parentGames * 100) : 0;
      var decided = n.wins + n.losses;
      var wr = decided ? Math.round(n.wins / decided * 100) + '%' : '\u2013';
      var html = '<b>' + esc(n.label) + '</b> ' + n.games + ' games \u00b7 ' + share +
        '% of parent \u00b7 ' + n.wins + '-' + n.losses + ' \u00b7 ' + wr +
        ' \u00b7 ' + clock(n.ms);
      if (diff) {
        if (n.base === null) {
          html += ' \u00b7 new vs overall';
        } else {
          var pts = Math.round((n.parentGames > 0 ? n.games / n.parentGames : 0) * 100 -
            n.base * 100);
          html += ' \u00b7 ' + (pts > 0 ? '+' : '') + pts + ' vs overall';
        }
      }
      tip.innerHTML = html;
      tip.hidden = false;
      var wr2 = wrap.getBoundingClientRect(), cr = rect.getBoundingClientRect();
      var left = cr.left - wr2.left + cr.width / 2 + 8;
      if (left + tip.offsetWidth > wr2.width - 4) left = wr2.width - tip.offsetWidth - 4;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, cr.top - wr2.top - 6) + 'px';
      if (pinned < 0) showSci(i);
    });
    host.addEventListener('mouseleave', function () {
      tip.hidden = true;
      Array.prototype.forEach.call(host.querySelectorAll('.ice-box'), function (r) {
        r.style.opacity = '1';
      });
      if (pinned < 0) resetSci();
    });
    host.addEventListener('contextmenu', function (e) {
      e.preventDefault();
      var rect = e.target;
      if (rect.classList && rect.classList.contains('ice-box')) {
        var i = +rect.getAttribute('data-i');
        setPin(i === pinned ? -1 : i);
      } else {
        setPin(-1);
      }
    });

    if (typeof IntersectionObserver === 'undefined') {
      render();
    } else {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) { render(); io.disconnect(); }
        });
      });
      io.observe(wrap);
    }
  });
})();
