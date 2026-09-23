(function () {
  var DOT = { buildings: '--s1', units: '--s2', heroes: '--s3' };

  function esc(s) { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
  function clock(seconds) {
    if (seconds === null || seconds === undefined) return '-';
    var m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + (s < 10 ? '0' : '') + s;
  }
  // The tables' diverging win-rate bar, rebuilt in JS from a node's win-loss split so the
  // Explorer reads the same as the openings table above it; an undecided node shows the dash.
  function bar(node) {
    var decided = node.wins + node.losses;
    if (!decided) return '<span class="na">-</span>';
    var rate = node.wins / decided;
    var span = Math.abs(rate - 0.5) * 100;
    var side = rate >= 0.5 ? 'above' : 'below';
    return '<span class="bar"><span class="track"><span class="fill ' + side +
      '" style="width:' + span.toFixed(0) + '%"></span><i></i></span>' +
      '<span class="pct">' + Math.round(rate * 100) + '%</span></span>';
  }

  // The share-vs-overall annotation for a diff row: the delta between this node's share of its
  // parent and the baseline's (`base_share`) in points, coloured like the tables' deltas, or a
  // `NEW` badge when the step is absent in the faction overall (base_share null).
  function vsOverall(node, parentGames) {
    if (node.base_share === null || node.base_share === undefined) {
      return '<span class="bo-vs"><span class="badge">NEW</span></span>';
    }
    var share = parentGames > 0 ? node.games / parentGames : 0;
    var points = Math.round(share * 100 - node.base_share * 100);
    var cls = points > 0 ? 'up' : points < 0 ? 'down' : 'even';
    var text = (points > 0 ? '+' : '') + points;
    return '<span class="bo-vs"><span class="delta ' + cls + '">' + text + '</span></span>';
  }

  Array.prototype.forEach.call(document.querySelectorAll('details.botree'), function (details) {
    var root = JSON.parse(details.querySelector('script.bo-data').textContent);
    var diff = !!root.diff;
    var host = details.querySelector('.bo-rows');
    var rows = [];
    var rendered = false;

    // A row is visible only while every real ancestor is expanded; the synthetic root (parent
    // of the depth-1 rows) is always expanded, so the top level always shows.
    function isVisible(row) {
      var p = row.parent;
      while (p) {
        if (!p.expanded) return false;
        p = p.parent;
      }
      return true;
    }
    function refresh() {
      rows.forEach(function (row) {
        row.el.hidden = !isVisible(row);
        if (row.hasKids) row.mark.textContent = row.expanded ? '\u25BE' : '\u25B8';
      });
    }
    function makeRow(node, depth, parentGames, hasKids) {
      var el = document.createElement('div');
      el.className = 'bo-row' + (hasKids ? ' bo-open' : '');
      el.style.marginLeft = ((depth - 1) * 18) + 'px';
      var share = parentGames > 0 ? Math.round(node.games / parentGames * 100) : 0;
      var count = node.median_count > 1 ? ' \u00d7' + node.median_count : '';
      var dot = DOT[node.category] || '--muted';
      el.innerHTML =
        '<span class="bo-mark">' + (hasKids ? '\u25B8' : '') + '</span>' +
        '<span class="bo-dot" style="background: var(' + dot + ')"></span>' +
        '<span class="bo-label">' + esc(node.label) + count + '</span>' +
        '<span class="bo-share">' + share + '%</span>' +
        (diff ? vsOverall(node, parentGames) : '') +
        '<span class="bo-games">' + node.games + '</span>' +
        '<span class="bo-wl">' + node.wins + '-' + node.losses + '</span>' +
        bar(node) +
        '<span class="bo-time">' + clock(node.median_seconds) + '</span>';
      return el;
    }
    function walk(node, depth, parentGames, parent) {
      var kids = node.children || [];
      var maxKid = 0;
      kids.forEach(function (c) {
        if (c.games > maxKid) maxKid = c.games;
      });
      var hasKids = kids.length > 0;
      var expanded = hasKids &&
        (depth === 0 || (node.games > 0 && maxKid / node.games >= 0.6));
      var row;
      if (depth === 0) {
        row = { expanded: true, parent: null };  // the synthetic root
      } else {
        var el = makeRow(node, depth, parentGames, hasKids);
        row = { el: el, expanded: expanded, hasKids: hasKids, parent: parent,
                mark: el.querySelector('.bo-mark') };
        if (hasKids) {
          (function (r) {
            el.addEventListener('click', function () { r.expanded = !r.expanded; refresh(); });
          })(row);
        }
        rows.push(row);
        host.appendChild(el);
      }
      kids.forEach(function (c) { walk(c, depth + 1, node.games, row); });
    }
    function render() {
      if (rendered) return;
      rendered = true;
      walk(root, 0, root.games, null);
      refresh();
    }

    details.addEventListener('toggle', function () {
      if (details.open) render();
    });
    if (details.open) render();
  });
})();
