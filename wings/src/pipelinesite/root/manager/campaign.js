(function () {
  function csrfToken() {
    var node = document.querySelector('[name=csrfmiddlewaretoken]');
    return node ? node.value : '';
  }

  function setDispatchEnabled(form, allowed, message) {
    if (!form) {
      return;
    }
    form.dataset.dispatchAllowed = allowed ? '1' : '0';
    var button = form.querySelector('button[type=submit]');
    var box = form.querySelector('input[name=rerun_all]');
    if (button) {
      button.disabled = !allowed;
    }
    if (box) {
      box.disabled = !allowed;
    }
    var note = document.querySelector('[data-dispatch-message]');
    if (note && message) {
      note.textContent = message;
    }
  }

  function pollStatus(url) {
    var nodes = document.querySelectorAll('[data-stage-key]');
    if (!nodes.length) {
      return;
    }
    function apply(data) {
      (data.stages || []).forEach(function (stage) {
        var chip = document.querySelector('[data-stage-key="' + stage.key + '"]');
        if (!chip) {
          return;
        }
        var state = chip.querySelector('[data-stage-state]');
        var dur = chip.querySelector('[data-stage-duration]');
        if (state) {
          state.textContent = stage.state;
          state.className = 'state state-' + stage.state;
        }
        if (dur) {
          dur.textContent = stage.duration || '—';
        }
      });
      var jobState = document.querySelector('[data-job-state]');
      if (jobState && data.job) {
        jobState.textContent = data.job.state;
        jobState.className = 'state state-' + data.job.state;
      }
      if (data.dispatch) {
        setDispatchEnabled(
          document.querySelector('[data-dispatch-form]'),
          !!data.dispatch.allowed,
          data.dispatch.message
        );
      }
      window.setTimeout(fetchOnce, 4000);
    }
    function fetchOnce() {
      fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (resp) { return resp.json(); })
        .then(apply)
        .catch(function () {
          window.setTimeout(fetchOnce, 8000);
        });
    }
    fetchOnce();
  }

  function setupDispatch(form) {
    if (!form) {
      return;
    }
    form.addEventListener('submit', function (event) {
      if (!form.dataset.ajax) {
        if (form.dataset.dispatchAllowed === '0') {
          event.preventDefault();
        }
        return;
      }
      event.preventDefault();
      if (form.dataset.dispatchAllowed === '0') {
        return;
      }
      setDispatchEnabled(form, false, 'Starting job…');
      var body = new FormData(form);
      fetch(form.action, {
        method: 'POST',
        body: body,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrfToken()
        }
      }).then(function (resp) { return resp.json().then(function (data) {
        if (!resp.ok) {
          setDispatchEnabled(form, false, data.error || 'Could not dispatch job');
          return;
        }
        window.location.reload();
      }); }).catch(function () {
        setDispatchEnabled(form, false, 'Could not dispatch job');
      });
    });
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]);
    });
  }

  function pad2(n) {
    return (n < 10 ? '0' : '') + n;
  }

  function formatRA(ra) {
    var hours = ((Number(ra) / 15) % 24 + 24) % 24;
    var hh = Math.floor(hours);
    var minutes = (hours - hh) * 60;
    var mm = Math.floor(minutes);
    var ss = (minutes - mm) * 60;
    return pad2(hh) + ':' + pad2(mm) + ':' + ss.toFixed(3).padStart(6, '0');
  }

  function formatDec(dec) {
    var sign = Number(dec) >= 0 ? '+' : '-';
    var adec = Math.abs(Number(dec));
    var dd = Math.floor(adec);
    var minutes = (adec - dd) * 60;
    var mm = Math.floor(minutes);
    var ss = (minutes - mm) * 60;
    return sign + pad2(dd) + ':' + pad2(mm) + ':' + ss.toFixed(2).padStart(5, '0');
  }

  function formatSky(ra, dec) {
    if (ra == null || dec == null || !isFinite(ra) || !isFinite(dec)) {
      return '';
    }
    return formatRA(ra) + ' ' + formatDec(dec);
  }

  function formatMag(row) {
    if (!row) {
      return '—';
    }
    if (row.is_limit && row.limit_mag != null && isFinite(row.limit_mag)) {
      return '< ' + Number(row.limit_mag).toFixed(3) + ' AB mag (3σ)';
    }
    if (row.mag == null || !isFinite(row.mag)) {
      return '—';
    }
    var text = Number(row.mag).toFixed(3);
    if (row.magerr != null && isFinite(row.magerr)) {
      text += ' ± ' + Number(row.magerr).toFixed(3);
    }
    return text + ' AB mag';
  }

  function instrumentKey(value) {
    var text = String(value || '').toUpperCase();
    if (text.indexOf('WFPC2') >= 0) {
      return 'WFPC2';
    }
    if (text.indexOf('WFC3') >= 0) {
      return 'WFC3';
    }
    if (text.indexOf('ACS') >= 0) {
      return 'ACS';
    }
    return text.split('/')[0];
  }

  function pickReferenceMag(mags, meta) {
    var list = mags || [];
    var inst = instrumentKey(meta && meta.instrument);
    var filt = ((meta && meta.filter) || '').toUpperCase();
    if (!inst || !filt) {
      return null;
    }
    return list.filter(function (row) {
      return instrumentKey(row.instrument) === inst && (row.filter || '').toUpperCase() === filt;
    })[0] || null;
  }

  function tanPixToWorld(x, y, wcs) {
    if (!wcs || !wcs.crpix || !wcs.crval || !wcs.cd) {
      return null;
    }
    var dx = x - wcs.crpix[0];
    var dy = y - wcs.crpix[1];
    var xi = (wcs.cd[0][0] * dx + wcs.cd[0][1] * dy) * Math.PI / 180;
    var eta = (wcs.cd[1][0] * dx + wcs.cd[1][1] * dy) * Math.PI / 180;
    var ra0 = wcs.crval[0] * Math.PI / 180;
    var dec0 = wcs.crval[1] * Math.PI / 180;
    var rho = Math.hypot(xi, eta);
    if (rho < 1e-15) {
      return { ra: wcs.crval[0], dec: wcs.crval[1] };
    }
    var c = Math.atan(rho);
    var sinc = Math.sin(c);
    var cosc = Math.cos(c);
    var sinDec = Math.max(-1, Math.min(1, cosc * Math.sin(dec0) + eta * sinc * Math.cos(dec0) / rho));
    var dec = Math.asin(sinDec);
    var ra = ra0 + Math.atan2(xi * sinc, rho * Math.cos(dec0) * cosc - eta * Math.sin(dec0) * sinc);
    var raDeg = (ra * 180 / Math.PI % 360 + 360) % 360;
    return { ra: raDeg, dec: dec * 180 / Math.PI };
  }

  function tanWorldToPix(ra, dec, wcs) {
    if (!wcs || !wcs.crpix || !wcs.crval || !wcs.cd) {
      return null;
    }
    var ra0 = wcs.crval[0] * Math.PI / 180;
    var dec0 = wcs.crval[1] * Math.PI / 180;
    var raR = ra * Math.PI / 180;
    var decR = dec * Math.PI / 180;
    var cosc = Math.sin(dec0) * Math.sin(decR) + Math.cos(dec0) * Math.cos(decR) * Math.cos(raR - ra0);
    if (cosc <= 0) {
      return null;
    }
    var xi = Math.cos(decR) * Math.sin(raR - ra0) / cosc * 180 / Math.PI;
    var eta = (Math.cos(dec0) * Math.sin(decR) - Math.sin(dec0) * Math.cos(decR) * Math.cos(raR - ra0)) / cosc * 180 / Math.PI;
    var det = wcs.cd[0][0] * wcs.cd[1][1] - wcs.cd[0][1] * wcs.cd[1][0];
    if (Math.abs(det) < 1e-30) {
      return null;
    }
    return {
      x: wcs.crpix[0] + (wcs.cd[1][1] * xi - wcs.cd[0][1] * eta) / det,
      y: wcs.crpix[1] + (-wcs.cd[1][0] * xi + wcs.cd[0][0] * eta) / det
    };
  }

  function setupViewer(root, page) {
    if (!root) {
      return;
    }
    var scope = page || root;
    var canvas = root.querySelector('canvas');
    var hud = root.querySelector('[data-sky-hud]');
    var previewUrl = root.dataset.previewUrl;
    var sourcesUrl = root.dataset.sourcesUrl;
    var selectedImageId = root.dataset.imageId || '';
    var ctx = canvas.getContext('2d');
    var image = new Image();
    var sources = [];
    var gaiaStars = [];
    var gaiaInfo = null;
    var meta = null;
    var scale = 1;
    var tx = 0;
    var ty = 0;
    var drag = null;
    var dragged = false;
    var showQuality = true;
    var showCut = false;
    var showGaia = true;
    var selected = null;
    var selectedKind = null;

    function fit() {
      if (!image.width) {
        return;
      }
      var frame = canvas.parentElement || canvas;
      var box = frame.getBoundingClientRect();
      var width = Math.max(1, Math.floor(box.width || canvas.clientWidth || 640));
      var height = Math.max(520, Math.floor(box.height || 520));
      canvas.width = width;
      canvas.height = height;
      // Keep CSS size equal to the drawing buffer so mouse coords match pixels.
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      scale = Math.min(canvas.width / image.width, canvas.height / image.height);
      tx = (canvas.width - image.width * scale) / 2;
      ty = (canvas.height - image.height * scale) / 2;
    }

    function pointerPos(event) {
      var rect = canvas.getBoundingClientRect();
      var sx = canvas.width / Math.max(rect.width, 1e-6);
      var sy = canvas.height / Math.max(rect.height, 1e-6);
      return {
        x: (event.clientX - rect.left) * sx,
        y: (event.clientY - rect.top) * sy
      };
    }

    function visibleSources() {
      return sources.filter(function (src) {
        if (src.passed) {
          return showQuality;
        }
        return showCut;
      });
    }

    function sourceToCanvas(src) {
      if (!meta) {
        return { x: 0, y: 0 };
      }
      var fx = src.x;
      var fy = src.y;
      if (src.ra != null && src.dec != null && meta.wcs) {
        var pix = tanWorldToPix(Number(src.ra), Number(src.dec), meta.wcs);
        if (pix) {
          fx = pix.x;
          fy = pix.y;
        }
      }
      var px = (fx - 1) * meta.scale;
      var py = (meta.ny - fy) * meta.scale;
      return { x: tx + px * scale, y: ty + py * scale };
    }

    function drawGaiaMark(p, used, highlight) {
      var r = highlight ? 9 : (used ? 7 : 6);
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.strokeStyle = used ? 'rgba(242, 193, 78, 0.95)' : 'rgba(242, 193, 78, 0.55)';
      ctx.lineWidth = highlight ? 2 : 1.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(p.x - r - 2, p.y);
      ctx.lineTo(p.x + r + 2, p.y);
      ctx.moveTo(p.x, p.y - r - 2);
      ctx.lineTo(p.x, p.y + r + 2);
      ctx.stroke();
    }

    function draw() {
      ctx.fillStyle = '#f4f6f8';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      if (image.width) {
        ctx.drawImage(image, tx, ty, image.width * scale, image.height * scale);
      }
      visibleSources().forEach(function (src) {
        var p = sourceToCanvas(src);
        if (p.x < -20 || p.y < -20 || p.x > canvas.width + 20 || p.y > canvas.height + 20) {
          return;
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, src.passed ? 3.2 : 2.2, 0, Math.PI * 2);
        ctx.strokeStyle = src.passed ? 'rgba(30, 120, 220, 0.95)' : 'rgba(210, 120, 20, 0.55)';
        ctx.lineWidth = 1.25;
        ctx.stroke();
      });
      if (showGaia) {
        gaiaStars.forEach(function (star) {
          drawGaiaMark(sourceToCanvas(star), star.used, false);
        });
      }
      if (selected) {
        var p = sourceToCanvas(selected);
        if (selectedKind === 'gaia') {
          drawGaiaMark(p, true, true);
        } else {
          ctx.beginPath();
          ctx.arc(p.x, p.y, 6, 0, Math.PI * 2);
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 1.4;
          ctx.stroke();
        }
      }
    }

    function nearestIn(list, x, y, maxD) {
      var best = null;
      var bestD = maxD;
      list.forEach(function (src) {
        var p = sourceToCanvas(src);
        var d = Math.hypot(p.x - x, p.y - y);
        if (d < bestD) {
          best = src;
          bestD = d;
        }
      });
      return best ? { item: best, dist: bestD } : null;
    }

    function nearest(x, y) {
      var srcHit = nearestIn(visibleSources(), x, y, 18);
      var gaiaHit = showGaia ? nearestIn(gaiaStars, x, y, 22) : null;
      if (gaiaHit && (!srcHit || gaiaHit.dist <= srcHit.dist)) {
        return { kind: 'gaia', item: gaiaHit.item };
      }
      if (srcHit) {
        return { kind: 'source', item: srcHit.item };
      }
      return null;
    }

    function showSelected() {
      var box = scope.querySelector('[data-source-info]');
      if (!box) {
        return;
      }
      if (!selected) {
        box.textContent = 'Click a source to inspect it.';
        return;
      }
      if (selectedKind === 'gaia') {
        var residual = selected.residual_arcsec;
        box.innerHTML =
          '<div class="source-title">Gaia DR3' +
          (selected.source_id ? ' ' + esc(selected.source_id) : '') + '</div>' +
          '<div>RA/Dec = ' + esc(formatSky(selected.ra, selected.dec)) + '</div>' +
          '<div>RA/Dec (deg) = ' + Number(selected.ra).toFixed(6) + ', ' + Number(selected.dec).toFixed(6) + '</div>' +
          (selected.gmag != null ? '<div>G = ' + Number(selected.gmag).toFixed(3) + '</div>' : '') +
          '<div>x,y = ' + selected.x.toFixed(2) + ', ' + selected.y.toFixed(2) + '</div>' +
          '<div>' + (selected.used ? 'Used for absolute WCS' : 'On image, not matched') +
          (residual != null ? ' (' + residual.toFixed(3) + '″ residual)' : '') + '</div>';
        return;
      }
      var refMag = pickReferenceMag(selected.mags, meta);
      var wantName = [instrumentKey(meta && meta.instrument), ((meta && meta.filter) || '').toUpperCase()].filter(Boolean).join(' ');
      var magLine = refMag
        ? '<div class="mag-row">' + esc(refMag.name) + ' = ' + esc(formatMag(refMag)) + '</div>'
        : '<div class="mag-row">No ' + esc(wantName || 'displayed-filter') + ' AB magnitude in catalog</div>';
      box.innerHTML =
        '<div class="source-title">Source ' + selected.index + '</div>' +
        magLine +
        '<div>RA/Dec = ' + esc(formatSky(selected.ra, selected.dec)) + '</div>' +
        (selected.ra != null ? '<div>RA/Dec (deg) = ' + Number(selected.ra).toFixed(6) + ', ' + Number(selected.dec).toFixed(6) + '</div>' : '') +
        '<div>x,y = ' + selected.x.toFixed(2) + ', ' + selected.y.toFixed(2) + '</div>' +
        '<div>SNR = ' + selected.snr.toFixed(2) + '</div>' +
        '<div>sharp = ' + selected.sharp.toFixed(3) + '</div>' +
        '<div>crowd = ' + selected.crowd.toFixed(3) + '</div>' +
        (selected.chi != null ? '<div>χ² = ' + Number(selected.chi).toFixed(3) + '</div>' : '') +
        (selected.roundness != null ? '<div>round = ' + Number(selected.roundness).toFixed(3) + '</div>' : '') +
        '<div>type = ' + selected.type + (selected.passed ? ' (passed cuts)' : ' (rejected)') + '</div>';
    }

    function canvasToFits(mx, my) {
      if (!meta || !image.width) {
        return null;
      }
      var px = (mx - tx) / scale;
      var py = (my - ty) / scale;
      var fitsX = px / meta.scale + 1;
      var fitsY = meta.ny - py / meta.scale;
      return { x: fitsX, y: fitsY };
    }

    function updateHud(mx, my) {
      if (!hud) {
        return;
      }
      var pix = canvasToFits(mx, my);
      var wcs = meta && meta.wcs;
      var sky = pix && wcs ? tanPixToWorld(pix.x, pix.y, wcs) : null;
      if (!sky) {
        hud.textContent = '';
        hud.classList.add('is-empty');
        return;
      }
      hud.innerHTML = esc(formatSky(sky.ra, sky.dec)) +
        '<br>' + sky.ra.toFixed(6) + '&nbsp;&nbsp;' + sky.dec.toFixed(6);
      hud.classList.remove('is-empty');
    }

    canvas.addEventListener('wheel', function (event) {
      event.preventDefault();
      var pos = pointerPos(event);
      var factor = event.deltaY < 0 ? 1.12 : 0.89;
      var next = Math.min(18, Math.max(0.2, scale * factor));
      // Keep the sky point under the cursor fixed while zooming.
      tx = pos.x - (pos.x - tx) * (next / scale);
      ty = pos.y - (pos.y - ty) * (next / scale);
      scale = next;
      draw();
    }, { passive: false });

    canvas.addEventListener('mousedown', function (event) {
      var pos = pointerPos(event);
      drag = { x: pos.x, y: pos.y, tx: tx, ty: ty };
      dragged = false;
      root.classList.add('is-dragging');
    });
    window.addEventListener('mouseup', function () {
      drag = null;
      root.classList.remove('is-dragging');
    });
    window.addEventListener('mousemove', function (event) {
      var rect = canvas.getBoundingClientRect();
      var pos = pointerPos(event);
      if (drag) {
        tx = drag.tx + (pos.x - drag.x);
        ty = drag.ty + (pos.y - drag.y);
        if (Math.abs(pos.x - drag.x) > 3 || Math.abs(pos.y - drag.y) > 3) {
          dragged = true;
        }
        draw();
      }
      if (event.clientX >= rect.left && event.clientX <= rect.right &&
          event.clientY >= rect.top && event.clientY <= rect.bottom) {
        updateHud(pos.x, pos.y);
      }
    });
    canvas.addEventListener('mouseleave', function () {
      if (hud) {
        hud.textContent = '';
        hud.classList.add('is-empty');
      }
    });
    canvas.addEventListener('click', function (event) {
      if (dragged) {
        return;
      }
      var pos = pointerPos(event);
      var hit = nearest(pos.x, pos.y);
      selected = hit ? hit.item : null;
      selectedKind = hit ? hit.kind : null;
      showSelected();
      draw();
    });

    function bindToggle(button, apply) {
      if (!button) {
        return;
      }
      button.addEventListener('click', function () {
        var on = button.getAttribute('aria-pressed') !== 'true';
        button.setAttribute('aria-pressed', on ? 'true' : 'false');
        button.classList.toggle('is-on', on);
        apply(on);
        draw();
      });
    }
    bindToggle(scope.querySelector('[data-show-quality]'), function (on) { showQuality = on; });
    bindToggle(scope.querySelector('[data-show-cut]'), function (on) { showCut = on; });
    bindToggle(scope.querySelector('[data-show-gaia]'), function (on) { showGaia = on; });

    window.addEventListener('resize', function () {
      fit();
      draw();
    });

    function withImage(url, imageId) {
      if (!url) {
        return url;
      }
      var resolved = new URL(url, window.location.origin);
      if (imageId) {
        resolved.searchParams.set('image', imageId);
      } else {
        resolved.searchParams.delete('image');
      }
      return resolved.pathname + resolved.search;
    }

    function loadView(imageId) {
      selectedImageId = imageId || '';
      root.dataset.imageId = selectedImageId;
      var nextPreview = withImage(previewUrl, selectedImageId);
      var nextSources = withImage(sourcesUrl, selectedImageId);
      var fits = scope.querySelector('[data-reference-fits]');
      if (fits) {
        fits.href = withImage(fits.getAttribute('href').split('?')[0], selectedImageId);
      }
      var keepIndex = selected && selectedKind === 'source' ? selected.index : null;
      var keepGaia = selected && selectedKind === 'gaia' ? selected.source_id : null;
      Promise.all([
        new Promise(function (resolve, reject) {
          image.onload = resolve;
          image.onerror = reject;
          image.src = nextPreview;
        }),
        fetch(nextSources).then(function (resp) { return resp.json(); })
      ]).then(function (parts) {
        var payload = parts[1];
        meta = payload.reference;
        sources = payload.sources || [];
        gaiaInfo = payload.gaia || {};
        gaiaStars = gaiaInfo.stars || [];
        if (keepIndex != null) {
          selected = sources.filter(function (src) { return src.index === keepIndex; })[0] || null;
          selectedKind = selected ? 'source' : null;
        } else if (keepGaia != null) {
          selected = gaiaStars.filter(function (star) { return star.source_id === keepGaia; })[0] || null;
          selectedKind = selected ? 'gaia' : null;
        } else {
          selected = null;
          selectedKind = null;
        }
        var count = scope.querySelector('[data-source-count]');
        if (count) {
          if (payload.n_sources) {
            count.textContent = payload.n_passed + ' / ' + payload.n_sources + ' pass quality cuts';
          } else {
            count.textContent = 'No DOLPHOT catalog yet';
          }
        }
        var heading = scope.querySelector('[data-reference-heading]');
        if (heading && meta && meta.heading) {
          heading.textContent = meta.heading;
        }
        var gaiaCount = scope.querySelector('[data-gaia-count]');
        if (gaiaCount) {
          gaiaCount.textContent = payload.wcs_quality || (
            gaiaInfo.n_on_image
              ? gaiaInfo.n_used + ' / ' + gaiaInfo.n_on_image + ' Gaia stars used for absolute WCS'
              : 'No Gaia alignment stars on this image'
          );
        }
        showSelected();
        fit();
        draw();
      }).catch(function () {
        ctx.fillStyle = '#333';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      });
    }

    var picker = scope.querySelector('[data-reference-select]');
    if (picker) {
      picker.addEventListener('change', function () {
        loadView(picker.value);
      });
      if (picker.value) {
        selectedImageId = picker.value;
      }
    }

    loadView(selectedImageId);
  }

  function cellSortValue(cell, type) {
    var text = (cell && cell.textContent ? cell.textContent : '').replace(/\s+/g, ' ').trim();
    if (!text || text === '—') {
      return null;
    }
    if (type === 'number') {
      var number = parseFloat(text.replace(/,/g, ''));
      return isNaN(number) ? null : number;
    }
    return text.toLowerCase();
  }

  function setupSortableTables(scope) {
    (scope.querySelectorAll('[data-sortable]') || []).forEach(function (table) {
      var headers = table.querySelectorAll('thead th[data-sort]');
      headers.forEach(function (header, index) {
        header.setAttribute('role', 'button');
        header.tabIndex = 0;
        header.addEventListener('click', function () {
          sortTable(table, headers, index);
        });
        header.addEventListener('keydown', function (event) {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            sortTable(table, headers, index);
          }
        });
      });
    });
  }

  function sortTable(table, headers, index) {
    var body = table.tBodies[0];
    if (!body) {
      return;
    }
    var header = headers[index];
    var type = header.getAttribute('data-sort') || 'text';
    var next = header.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
    headers.forEach(function (node) {
      node.removeAttribute('aria-sort');
    });
    header.setAttribute('aria-sort', next);
    var rows = Array.prototype.slice.call(body.rows).filter(function (row) {
      return row.cells.length > 1;
    });
    rows.sort(function (left, right) {
      var a = cellSortValue(left.cells[index], type);
      var b = cellSortValue(right.cells[index], type);
      if (a === null && b === null) {
        return 0;
      }
      if (a === null) {
        return 1;
      }
      if (b === null) {
        return -1;
      }
      if (a < b) {
        return next === 'ascending' ? -1 : 1;
      }
      if (a > b) {
        return next === 'ascending' ? 1 : -1;
      }
      return 0;
    });
    rows.forEach(function (row) {
      body.appendChild(row);
    });
  }

  function fmtNum(value, digits) {
    if (value == null || value === '' || !isFinite(Number(value))) {
      return '—';
    }
    return Number(value).toFixed(digits);
  }

  function renderImages(root, images, nImages) {
    var body = root.querySelector('[data-images-body]');
    var count = root.querySelector('[data-image-count]');
    if (count && nImages != null) {
      count.textContent = nImages;
    }
    if (!body) {
      return;
    }
    if (!images || !images.length) {
      body.innerHTML = '<tr data-images-placeholder><td colspan="10">' +
        (nImages ? 'Loading image metadata…' : 'No downloaded science images yet.') +
        '</td></tr>';
      return;
    }
    body.innerHTML = images.map(function (image) {
      return '<tr>' +
        '<td>' + esc(image.filename) + '</td>' +
        '<td>' + esc(image.telescope) + '</td>' +
        '<td>' + esc(image.instrument) + '</td>' +
        '<td>' + esc(image.filter) + '</td>' +
        '<td>' + (image.exptime != null && isFinite(Number(image.exptime)) ? Number(image.exptime).toFixed(1) : '—') + '</td>' +
        '<td>' + esc(image.date_obs || '—') + '</td>' +
        '<td>' + fmtNum(image.ra, 5) + '</td>' +
        '<td>' + fmtNum(image.dec, 5) + '</td>' +
        '<td>' + esc(image.size_display || '—') + '</td>' +
        '<td>' + esc(image.obsid || '') + '</td>' +
        '</tr>';
    }).join('');
  }

  function renderCatalogs(root, catalogs) {
    var card = root.querySelector('[data-catalogs-card]');
    var body = root.querySelector('[data-catalogs-body]');
    if (!body) {
      return;
    }
    if (!catalogs || !catalogs.length) {
      return;
    }
    var template = card ? card.getAttribute('data-hdf5-template') : '';
    body.innerHTML = catalogs.map(function (cat) {
      var href = template ? template.replace('__STEM__', encodeURIComponent(cat.stem || '')) : '#';
      var cuts = cat.cuts || {};
      var extra = cuts.snr_min != null ? ', SNR ≥ ' + esc(cuts.snr_min) : '';
      return '<p><code>' + esc(cat.name) + '</code> ' +
        '<a class="btn btn-sm btn-outline-secondary" href="' + esc(href) + '">Download HDF5</a> ' +
        '<strong>' + esc(cat.n_before) + '</strong> sources before cuts, ' +
        '<strong>' + esc(cat.n_after) + '</strong> after type ∈ ' +
        esc((cuts.types || []).join(', ')) +
        ', |sharp| ≤ ' + esc(cuts.sharp_max) +
        ', crowd ≤ ' + esc(cuts.crowd_max) + extra + '.</p>';
    }).join('');
  }

  function renderMosaics(root, mosaics, selectedId) {
    var picker = root.querySelector('[data-mosaic-picker]');
    var select = root.querySelector('[data-reference-select]');
    if (!select || !mosaics || !mosaics.length) {
      return;
    }
    var current = selectedId || select.value;
    select.innerHTML = mosaics.map(function (image) {
      var selected = image.id === current || image.selected ? ' selected' : '';
      return '<option value="' + esc(image.id) + '"' + selected + '>' +
        esc(image.option_label || image.label || image.filename) + '</option>';
    }).join('');
    if (picker) {
      picker.hidden = false;
    }
  }

  function loadInventory(root) {
    var url = root.dataset.inventoryUrl;
    if (!url) {
      return;
    }
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (resp) { return resp.json(); })
      .then(function (data) {
        renderImages(root, data.images || [], data.n_images);
        renderCatalogs(root, data.catalogs || []);
        renderMosaics(root, data.mosaics || [], (data.reference || {}).id);
        var heading = root.querySelector('[data-reference-heading]');
        if (heading && data.reference && data.reference.heading) {
          heading.textContent = data.reference.heading;
        }
        var viewer = root.querySelector('[data-viewer]');
        if (viewer && data.reference && data.reference.id && !viewer.dataset.imageId) {
          viewer.dataset.imageId = data.reference.id;
        }
      })
      .catch(function () {
        var body = root.querySelector('[data-images-body]');
        if (body && body.querySelector('[data-images-placeholder]')) {
          body.innerHTML = '<tr><td colspan="10">Could not load image metadata.</td></tr>';
        }
      });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.querySelector('[data-campaign-root]');
    if (!root) {
      return;
    }
    pollStatus(root.dataset.statusUrl);
    setupDispatch(root.querySelector('[data-dispatch-form]'));
    setupViewer(root.querySelector('[data-viewer]'), root);
    setupSortableTables(root);
    loadInventory(root);
  });
})();
