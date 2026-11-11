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

  function formatMagCell(row) {
    if (!row) {
      return '—';
    }
    if (row.is_limit && row.limit_mag != null && isFinite(row.limit_mag)) {
      return '< ' + Number(row.limit_mag).toFixed(3) + ' (3σ)';
    }
    if (row.mag == null || !isFinite(row.mag)) {
      return '—';
    }
    return Number(row.mag).toFixed(3);
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

  function formatMjd(value) {
    if (value == null || !isFinite(Number(value))) {
      return '—';
    }
    return Number(value).toFixed(5);
  }

  function photometryTableHtml(title, rows, mjdLabel) {
    if (!rows || !rows.length) {
      return '<div class="photometry-section"><h4>' + esc(title) + '</h4>' +
        '<p class="photometry-empty">No measurements.</p></div>';
    }
    var body = rows.map(function (row) {
      return '<tr>' +
        '<td>' + esc(formatMjd(row.mjd)) + '</td>' +
        '<td>' + esc(row.instrument || '—') + '</td>' +
        '<td>' + esc(row.filter || '—') + '</td>' +
        '<td>' + esc(formatMagCell(row)) + '</td>' +
        '<td>' + (row.is_limit || row.magerr == null || !isFinite(row.magerr)
          ? '—'
          : Number(row.magerr).toFixed(3)) + '</td>' +
        '</tr>';
    }).join('');
    return '<div class="photometry-section"><h4>' + esc(title) + '</h4>' +
      '<div class="photometry-table-wrap"><table class="photometry-table"><thead><tr>' +
      '<th>' + esc(mjdLabel) + '</th><th>Instrument</th><th>Filter</th>' +
      '<th>Magnitude</th><th>Uncertainty</th></tr></thead><tbody>' +
      body + '</tbody></table></div></div>';
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

  function pixelScaleArcsec(wcs) {
    if (!wcs || !wcs.cd) {
      return null;
    }
    var sx = Math.hypot(wcs.cd[0][0], wcs.cd[1][0]) * 3600;
    var sy = Math.hypot(wcs.cd[0][1], wcs.cd[1][1]) * 3600;
    var value = (sx + sy) / 2;
    return value > 0 ? value : null;
  }

  function parseSkyPair(raText, decText) {
    var raRaw = String(raText || '').trim();
    var decRaw = String(decText || '').trim();
    if (!raRaw && !decRaw) {
      return null;
    }
    // Allow a single "RA Dec" paste into the RA field.
    if (raRaw && !decRaw) {
      var parts = raRaw.replace(/,/g, ' ').trim().split(/\s+/);
      if (parts.length >= 2) {
        var mid = Math.floor(parts.length / 2);
        raRaw = parts.slice(0, mid).join(' ');
        decRaw = parts.slice(mid).join(' ');
      }
    }
    if (!raRaw || !decRaw) {
      return null;
    }
    var raNum = Number(raRaw);
    var decNum = Number(decRaw);
    if (isFinite(raNum) && isFinite(decNum) && !/[hms:]/i.test(raRaw + decRaw)) {
      return { ra: raNum, dec: decNum };
    }
    var text = (raRaw + ' ' + decRaw).replace(/:/g, ' ');
    var match = text.match(
      /(\d+)\s+(\d+)\s+([\d.]+)\s+([+-])\s*(\d+)\s+(\d+)\s+([\d.]+)/
    );
    if (!match) {
      return null;
    }
    var ra = (Number(match[1]) + Number(match[2]) / 60 + Number(match[3]) / 3600) * 15;
    var dec = Number(match[5]) + Number(match[6]) / 60 + Number(match[7]) / 3600;
    if (match[4] === '-') {
      dec = -dec;
    }
    return { ra: ra, dec: dec };
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
    var photometryUrlTemplate = root.dataset.photometryUrlTemplate || '';
    var previewStaticBase = root.dataset.previewStatic || '';
    var selectedImageId = root.dataset.imageId || '';
    var ctx = canvas.getContext('2d');
    var displayBitmap = null;
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
    var sourcesCache = {};
    var bitmapCache = {};
    var rejectsLoaded = {};
    var prefetchStarted = false;
    var photometryCache = {};
    var photometryPanel = scope.querySelector('[data-photometry-panel]');
    var photometryTitle = scope.querySelector('[data-photometry-title]');
    var photometryStatus = scope.querySelector('[data-photometry-status]');
    var photometryTables = scope.querySelector('[data-photometry-tables]');
    var gotoForm = scope.querySelector('[data-goto-sky]');
    var gotoRa = scope.querySelector('[data-goto-ra]');
    var gotoDec = scope.querySelector('[data-goto-dec]');
    var gotoStatus = scope.querySelector('[data-goto-status]');
    var gotoClear = scope.querySelector('[data-goto-clear]');
    var gotoMark = null;
    var GOTO_BOX_ARCSEC = 5;
    var GOTO_MARK_ARCSEC = 0.5;
    var GOTO_MAX_SCALE = 48;

    function displaySize() {
      if (displayBitmap) {
        return { width: displayBitmap.width, height: displayBitmap.height };
      }
      return { width: 0, height: 0 };
    }

    function fit() {
      var size = displaySize();
      if (!size.width) {
        return;
      }
      var frame = canvas.parentElement || canvas;
      var box = frame.getBoundingClientRect();
      // Fit the mosaic into the frame width without letterboxing empty bars into
      // the canvas — those bars looked like vignetted / missing data.
      var width = Math.max(1, Math.floor(box.width || canvas.clientWidth || 640));
      scale = width / size.width;
      var height = Math.max(1, Math.floor(size.height * scale));
      canvas.width = width;
      canvas.height = height;
      // Keep CSS size equal to the drawing buffer so mouse coords match pixels.
      canvas.style.width = width + 'px';
      canvas.style.height = height + 'px';
      tx = 0;
      ty = 0;
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

    function setGotoStatus(message, isError) {
      if (!gotoStatus) {
        return;
      }
      gotoStatus.textContent = message || 'Zooms to 5″ × 5″ with a 0.5″ marker';
      gotoStatus.classList.toggle('is-error', !!isError);
    }

    function skyToDisplay(ra, dec) {
      if (!meta || !meta.wcs) {
        return null;
      }
      var pix = tanWorldToPix(Number(ra), Number(dec), meta.wcs);
      if (!pix) {
        return null;
      }
      return {
        x: (pix.x - 1) * meta.scale,
        y: (meta.ny - pix.y) * meta.scale,
        fitsX: pix.x,
        fitsY: pix.y
      };
    }

    function gotoSky(ra, dec) {
      if (!meta || !meta.wcs || !displayBitmap) {
        setGotoStatus('Mosaic WCS is not ready yet.', true);
        return false;
      }
      var pixScale = pixelScaleArcsec(meta.wcs);
      if (!pixScale) {
        setGotoStatus('Could not determine the mosaic plate scale.', true);
        return false;
      }
      var disp = skyToDisplay(ra, dec);
      if (!disp) {
        setGotoStatus('Coordinates are outside the mosaic WCS.', true);
        return false;
      }
      if (disp.fitsX < 1 || disp.fitsY < 1 || disp.fitsX > meta.nx || disp.fitsY > meta.ny) {
        setGotoStatus('Coordinates fall outside the mosaic footprint.', true);
        return false;
      }
      var boxDisp = (GOTO_BOX_ARCSEC / pixScale) * meta.scale;
      if (!(boxDisp > 0)) {
        setGotoStatus('Could not size the 5″ zoom box.', true);
        return false;
      }
      var view = Math.max(40, Math.min(canvas.width, canvas.height));
      scale = Math.min(GOTO_MAX_SCALE, Math.max(0.2, view / boxDisp));
      tx = canvas.width / 2 - disp.x * scale;
      ty = canvas.height / 2 - disp.y * scale;
      gotoMark = { ra: Number(ra), dec: Number(dec) };
      setGotoStatus(
        'Centered on ' + formatSky(gotoMark.ra, gotoMark.dec) + ' · 5″ field · 0.5″ marker'
      );
      draw();
      return true;
    }

    function clearGotoMark() {
      gotoMark = null;
      setGotoStatus();
      draw();
    }

    function drawGotoMark() {
      if (!gotoMark || !meta || !meta.wcs) {
        return;
      }
      var p = sourceToCanvas(gotoMark);
      var pixScale = pixelScaleArcsec(meta.wcs);
      if (!pixScale) {
        return;
      }
      var r = Math.max(3, (GOTO_MARK_ARCSEC / pixScale) * meta.scale * scale);
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(220, 40, 70, 0.95)';
      ctx.lineWidth = 1.8;
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(p.x - r - 4, p.y);
      ctx.lineTo(p.x + r + 4, p.y);
      ctx.moveTo(p.x, p.y - r - 4);
      ctx.lineTo(p.x, p.y + r + 4);
      ctx.strokeStyle = 'rgba(220, 40, 70, 0.85)';
      ctx.lineWidth = 1.2;
      ctx.stroke();
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
      var size = displaySize();
      if (displayBitmap && size.width) {
        ctx.drawImage(displayBitmap, tx, ty, size.width * scale, size.height * scale);
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
      drawGotoMark();
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

    function photometryUrlFor(index) {
      if (!photometryUrlTemplate) {
        return '';
      }
      return String(photometryUrlTemplate).replace(/\/sources\/0\//, '/sources/' + index + '/');
    }

    function resetPhotometryPanel(message) {
      if (photometryTitle) {
        photometryTitle.textContent = 'Source photometry';
      }
      if (photometryStatus) {
        photometryStatus.textContent = message || 'Click a DOLPHOT source to load its photometry.';
      }
      if (photometryTables) {
        photometryTables.innerHTML = '';
      }
    }

    function renderPhotometry(payload) {
      if (!photometryPanel || !photometryTables) {
        return;
      }
      if (photometryTitle) {
        photometryTitle.textContent = 'Source ' + payload.index + ' photometry';
      }
      if (photometryStatus) {
        photometryStatus.textContent =
          (payload.epochs || []).length + ' epoch measurement' +
          ((payload.epochs || []).length === 1 ? '' : 's') +
          ' · ' +
          (payload.combined || []).length + ' combined filter' +
          ((payload.combined || []).length === 1 ? '' : 's');
      }
      photometryTables.innerHTML =
        photometryTableHtml('Per-epoch photometry', payload.epochs || [], 'MJD') +
        photometryTableHtml('Combined by filter', payload.combined || [], 'Average MJD');
    }

    function openPhotometry() {
      if (!selected || selectedKind !== 'source' || selected.index == null) {
        resetPhotometryPanel(
          selectedKind === 'gaia'
            ? 'Gaia sources have no DOLPHOT photometry.'
            : 'Click a DOLPHOT source to load its photometry.'
        );
        return;
      }
      var index = selected.index;
      var cacheKey = selectedImageId + '|' + index;
      if (photometryCache[cacheKey]) {
        renderPhotometry(photometryCache[cacheKey]);
        return;
      }
      var url = photometryUrlFor(index);
      if (!url) {
        resetPhotometryPanel('Photometry endpoint is unavailable.');
        return;
      }
      if (selectedImageId) {
        url += (url.indexOf('?') >= 0 ? '&' : '?') + 'image=' + encodeURIComponent(selectedImageId);
      }
      if (photometryStatus) {
        photometryStatus.textContent = 'Loading photometry for source ' + index + '…';
      }
      if (photometryTables) {
        photometryTables.innerHTML = '';
      }
      fetch(url, { credentials: 'same-origin' }).then(function (resp) {
        if (!resp.ok) {
          throw new Error('photometry ' + resp.status);
        }
        return resp.json();
      }).then(function (payload) {
        photometryCache[cacheKey] = payload;
        if (selected && selectedKind === 'source' && selected.index === index) {
          renderPhotometry(payload);
        }
      }).catch(function () {
        if (photometryStatus) {
          photometryStatus.textContent = 'Could not load photometry for source ' + index + '.';
        }
      });
    }

    function showSelected() {
      var box = scope.querySelector('[data-source-info]');
      if (!box) {
        return;
      }
      if (!selected) {
        box.textContent = 'Click a source to inspect it.';
        openPhotometry();
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
        openPhotometry();
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
      openPhotometry();
    }

    function canvasToFits(mx, my) {
      var size = displaySize();
      if (!meta || !size.width) {
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
    resetPhotometryPanel();

    if (gotoForm) {
      gotoForm.addEventListener('submit', function (event) {
        event.preventDefault();
        var sky = parseSkyPair(gotoRa && gotoRa.value, gotoDec && gotoDec.value);
        if (!sky) {
          setGotoStatus('Enter RA/Dec as sexagesimal or decimal degrees.', true);
          return;
        }
        gotoSky(sky.ra, sky.dec);
      });
    }
    if (gotoClear) {
      gotoClear.addEventListener('click', function () {
        if (gotoRa) {
          gotoRa.value = '';
        }
        if (gotoDec) {
          gotoDec.value = '';
        }
        clearGotoMark();
      });
    }

    bindToggle(scope.querySelector('[data-show-quality]'), function (on) { showQuality = on; });
    bindToggle(scope.querySelector('[data-show-cut]'), function (on) {
      showCut = on;
      if (on) {
        ensureRejects(selectedImageId).then(function () { draw(); });
      }
    });
    bindToggle(scope.querySelector('[data-show-gaia]'), function (on) { showGaia = on; });

    window.addEventListener('resize', function () {
      if (gotoMark) {
        gotoSky(gotoMark.ra, gotoMark.dec);
      } else {
        fit();
        draw();
      }
    });

    function withImage(url, imageId, extra) {
      if (!url) {
        return url;
      }
      var resolved = new URL(url, window.location.origin);
      if (imageId) {
        resolved.searchParams.set('image', imageId);
      } else {
        resolved.searchParams.delete('image');
      }
      if (extra) {
        Object.keys(extra).forEach(function (key) {
          if (extra[key] == null || extra[key] === false) {
            resolved.searchParams.delete(key);
          } else {
            resolved.searchParams.set(key, String(extra[key]));
          }
        });
      }
      return resolved.pathname + resolved.search;
    }

    function applyPayload(payload, keepIndex, keepGaia) {
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
        if (payload.catalog_note) {
          count.textContent = payload.catalog_note;
        } else if (payload.n_sources) {
          count.textContent = payload.n_passed + ' / ' + payload.n_sources + ' pass quality cuts';
        } else {
          var filtLabel = [instrumentKey(meta && meta.instrument), ((meta && meta.filter) || '').toUpperCase()].filter(Boolean).join(' ');
          count.textContent = filtLabel
            ? ('No DOLPHOT catalog for ' + filtLabel + ' on this target')
            : 'No DOLPHOT catalog yet';
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
      if (gotoMark) {
        gotoSky(gotoMark.ra, gotoMark.dec);
      } else {
        fit();
        draw();
      }
    }

    function previewCandidates(imageId, staticUrls) {
      var urls = [];
      if (staticUrls) {
        if (staticUrls.webp) {
          urls.push(staticUrls.webp);
        }
        if (staticUrls.avif) {
          urls.push(staticUrls.avif);
        }
        if (staticUrls.jpeg) {
          urls.push(staticUrls.jpeg);
        }
      }
      if (previewStaticBase && imageId) {
        // Match preview._publish_static cache-bust when static_urls are absent.
        var bust = '?v=13';
        urls.push(previewStaticBase + imageId + '.webp' + bust);
        urls.push(previewStaticBase + imageId + '.avif' + bust);
        urls.push(previewStaticBase + imageId + '.jpg' + bust);
      }
      urls.push(withImage(previewUrl, imageId));
      var seen = {};
      return urls.filter(function (url) {
        if (!url || seen[url]) {
          return false;
        }
        seen[url] = true;
        return true;
      });
    }

    function fetchSources(imageId, opts) {
      var wantRejects = !!(opts && opts.rejects);
      var cacheKey = (imageId || '') + (wantRejects ? '|rejects' : '|pass');
      if (sourcesCache[cacheKey]) {
        return Promise.resolve(sourcesCache[cacheKey]);
      }
      var url = withImage(sourcesUrl, imageId, wantRejects ? { rejects: 1 } : null);
      return fetch(url, { credentials: 'same-origin' }).then(function (resp) {
        if (!resp.ok) {
          throw new Error('sources ' + resp.status);
        }
        return resp.json();
      }).then(function (payload) {
        sourcesCache[cacheKey] = payload;
        if (wantRejects) {
          rejectsLoaded[imageId || ''] = true;
          sourcesCache[(imageId || '') + '|pass'] = Object.assign({}, payload, {
            sources: (payload.sources || []).filter(function (src) { return src.passed; }),
            n_overlay: (payload.sources || []).filter(function (src) { return src.passed; }).length
          });
        }
        // Warm bitmap using static URLs from the payload when present.
        var staticUrls = payload && payload.reference && payload.reference.static_urls;
        loadBitmap(imageId, staticUrls).catch(function () {});
        return payload;
      });
    }

    function loadBitmap(imageId, staticUrls) {
      var key = imageId || '';
      if (bitmapCache[key]) {
        return Promise.resolve(bitmapCache[key]);
      }
      var candidates = previewCandidates(imageId, staticUrls);
      function tryNext(index) {
        if (index >= candidates.length) {
          return Promise.reject(new Error('preview unavailable'));
        }
        return fetch(candidates[index], { credentials: 'same-origin' }).then(function (resp) {
          if (!resp.ok) {
            return tryNext(index + 1);
          }
          return resp.blob().then(function (blob) {
            // createImageBitmap decodes off the main thread when the browser allows it.
            return createImageBitmap(blob).then(function (bitmap) {
              bitmapCache[key] = bitmap;
              return bitmap;
            });
          });
        }).catch(function () {
          return tryNext(index + 1);
        });
      }
      if (typeof createImageBitmap !== 'function') {
        return Promise.reject(new Error('createImageBitmap unsupported'));
      }
      return tryNext(0);
    }

    function ensureRejects(imageId) {
      if (rejectsLoaded[imageId || '']) {
        return Promise.resolve(sourcesCache[(imageId || '') + '|rejects']);
      }
      return fetchSources(imageId, { rejects: true }).then(function (payload) {
        if ((imageId || '') === (selectedImageId || '')) {
          sources = payload.sources || [];
        }
        return payload;
      });
    }

    function prefetchOthers() {
      if (prefetchStarted) {
        return;
      }
      prefetchStarted = true;
      var picker = scope.querySelector('[data-reference-select]');
      if (!picker) {
        return;
      }
      Array.prototype.forEach.call(picker.options, function (opt) {
        if (!opt.value || opt.value === selectedImageId) {
          return;
        }
        // Decode into ImageBitmap + JSON caches so later switches are memory-only.
        Promise.all([
          loadBitmap(opt.value),
          fetchSources(opt.value)
        ]).catch(function () {});
      });
    }

    function loadView(imageId) {
      selectedImageId = imageId || '';
      root.dataset.imageId = selectedImageId;
      var fits = scope.querySelector('[data-reference-fits]');
      if (fits) {
        fits.href = withImage(fits.getAttribute('href').split('?')[0], selectedImageId);
      }
      var keepIndex = selected && selectedKind === 'source' ? selected.index : null;
      var keepGaia = selected && selectedKind === 'gaia' ? selected.source_id : null;
      var cachedSources = sourcesCache[(selectedImageId || '') + (showCut ? '|rejects' : '|pass')];
      var cachedBitmap = bitmapCache[selectedImageId || ''];

      // Fast path: both assets already decoded in memory → draw only.
      if (cachedBitmap && cachedSources) {
        displayBitmap = cachedBitmap;
        applyPayload(cachedSources, keepIndex, keepGaia);
        window.setTimeout(prefetchOthers, 50);
        return;
      }

      var bitmapPromise = loadBitmap(selectedImageId).then(function (bitmap) {
        displayBitmap = bitmap;
        fit();
        draw();
        return bitmap;
      });
      var sourcesPromise = showCut
        ? fetchSources(selectedImageId, { rejects: true })
        : fetchSources(selectedImageId);
      Promise.all([bitmapPromise, sourcesPromise]).then(function (parts) {
        applyPayload(parts[1], keepIndex, keepGaia);
        window.setTimeout(prefetchOthers, 50);
      }).catch(function () {
        var count = scope.querySelector('[data-source-count]');
        if (count && !sources.length) {
          count.textContent = 'Catalog overlay unavailable';
        }
        if (displayBitmap) {
          fit();
          draw();
        }
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
