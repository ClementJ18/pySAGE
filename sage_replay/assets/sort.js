(function () {
  function key(cell) {
    var s = cell.textContent.trim();
    if (s === '' || s === '-' || s === '\u2013' || s === '\u2014') return null;
    var m = s.match(/^(\d+):([0-5]\d)$/);
    if (m) return (+m[1]) * 60 + (+m[2]);
    var f = parseFloat(s.replace(/^x/, '').replace(/%$/, '').replace(/,/g, ''));
    return isNaN(f) ? null : f;
  }
  function sortRows(table, col, numeric, dir) {
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    rows.forEach(function (r, i) { r._i = i; });
    rows.sort(function (a, b) {
      var r;
      if (numeric) {
        var ka = key(a.cells[col]), kb = key(b.cells[col]);
        if (ka === null && kb === null) r = 0;
        else if (ka === null) r = 1;
        else if (kb === null) r = -1;
        else r = ka - kb;
      } else {
        r = a.cells[col].textContent.trim().localeCompare(b.cells[col].textContent.trim());
      }
      return r ? (dir === 'asc' ? r : -r) : a._i - b._i;
    });
    rows.forEach(function (r) { body.appendChild(r); });
  }
  Array.prototype.forEach.call(document.querySelectorAll('table:not(.matrix)'), function (table) {
    if (!table.tHead || !table.tBodies.length) return;
    var ths = table.tHead.rows[0].cells;
    Array.prototype.forEach.call(ths, function (th, col) {
      th.classList.add('sortable');
      th.addEventListener('click', function () {
        var vals = 0, nums = 0;
        Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
          var c = row.cells[col];
          if (!c) return;
          if (c.textContent.trim() !== '') vals++;
          if (key(c) !== null) nums++;
        });
        var numeric = nums * 2 >= vals;
        var dir = th.dataset.dir === 'asc' ? 'desc'
                : th.dataset.dir === 'desc' ? 'asc'
                : (numeric ? 'desc' : 'asc');
        Array.prototype.forEach.call(ths, function (o) {
          delete o.dataset.dir;
          o.classList.remove('asc', 'desc');
        });
        th.dataset.dir = dir;
        th.classList.add(dir);
        sortRows(table, col, numeric, dir);
      });
    });
  });
})();
