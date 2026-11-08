/* WitMotion Console front end. Talks to the Python engine over JSON + SSE. */
(function () {
  'use strict';
  const { Level, Cube, Dial, Chart, History, MagScatter } = window.WitInstruments;
  const $ = (id) => document.getElementById(id);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ---- storage (per-browser conveniences only) -----------------------------
  const store = {
    get(k, d) { try { const v = localStorage.getItem('wit.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('wit.' + k, JSON.stringify(v)); } catch { /* ignore */ } },
  };

  // ---- state -----------------------------------------------------------------
  const state = {
    status: null,
    meta: null,
    sample: null,
    online: false,
    view: store.get('view', 'dashboard'),
    tare: store.get('tare', null),          // {roll, pitch, yaw} display offsets
    chartSet: store.get('chartSet', 'tilt'),
    chartWindow: store.get('chartWindow', 30),
    paused: null,                            // host time at which the chart froze
    magCal: false,
    regs: new Map(),                         // addr -> row
    dirty: true,
  };

  const hist = new History(24000, ['roll', 'pitch', 'yaw', 'ax', 'ay', 'az', 'an', 'gx', 'gy', 'gz', 'hx', 'hy', 'hz']);
  const level = new Level($('cv-level'));
  level.range = store.get('levelRange', 5);
  const cube = new Cube($('cv-cube'));
  const dial = new Dial($('cv-compass'));
  const chart = new Chart($('cv-chart-a'));
  const mag = new MagScatter($('cv-mag'));

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const CHART_SETS = {
    tilt: { unit: '°', minSpan: 0.2, series: [['roll', 'Roll', '--x', true], ['pitch', 'Pitch', '--y', true]] },
    yaw: { unit: '°', minSpan: 1, series: [['yaw', 'Yaw', '--z', true]] },
    acc: { unit: 'g', minSpan: 0.02, series: [['ax', 'X', '--x'], ['ay', 'Y', '--y'], ['az', 'Z', '--z']] },
    gyro: { unit: '°/s', minSpan: 1, series: [['gx', 'X', '--x'], ['gy', 'Y', '--y'], ['gz', 'Z', '--z']] },
    mag: { unit: 'LSB', minSpan: 50, series: [['hx', 'X', '--x'], ['hy', 'Y', '--y'], ['hz', 'Z', '--z']] },
  };

  // ---- helpers ------------------------------------------------------------------
  async function api(path, body) {
    const opts = body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    };
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch { /* empty */ }
    if (!r.ok) throw new Error((data && data.error) || `${r.status} ${r.statusText}`);
    return data;
  }

  function toast(msg, kind = '') {
    const el = document.createElement('div');
    el.className = 'toast ' + kind;
    el.textContent = msg;
    $('toasts').appendChild(el);
    setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
  }

  async function withBusy(btn, fn) {
    if (btn) { btn.disabled = true; btn.classList.add('busy'); }
    try { return await fn(); } catch (e) { toast(e.message, 'error'); return undefined; }
    finally { if (btn) { btn.disabled = false; btn.classList.remove('busy'); } }
  }

  const hex2 = (n) => '0x' + (n & 0xff).toString(16).toUpperCase().padStart(2, '0');
  const parseNum = (s) => {
    s = String(s).trim();
    if (!s) return NaN;
    return /^-?0x/i.test(s) ? (s.startsWith('-') ? -parseInt(s.slice(1), 16) : parseInt(s, 16)) : Number(s);
  };
  const f = (v, d) => (v == null || !isFinite(v) ? '—' : v.toFixed(d));
  const wrap180 = (a) => ((((a + 180) % 360) + 360) % 360) - 180;
  const bytes = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
  const connected = () => state.status && state.status.connection;

  // Angles after the optional display zero.
  function displayAngles(s) {
    if (!s) return null;
    const t = state.tare;
    if (!t) return { roll: s.roll, pitch: s.pitch, yaw: s.yaw, tilt: s.tilt };
    const roll = wrap180(s.roll - t.roll), pitch = wrap180(s.pitch - t.pitch), yaw = wrap180(s.yaw - t.yaw);
    const c = Math.cos(roll * Math.PI / 180) * Math.cos(pitch * Math.PI / 180);
    return { roll, pitch, yaw, tilt: Math.acos(Math.max(-1, Math.min(1, c))) * 180 / Math.PI };
  }

  // ---- tabs -----------------------------------------------------------------------
  function showView(name) {
    if (!$('view-' + name)) name = 'dashboard';
    state.view = name;
    store.set('view', name);
    qsa('.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.view === name)));
    qsa('.view').forEach((v) => { v.hidden = v.id !== 'view-' + name; });
    window.scrollTo(0, 0);
    state.magDrawn = false;
    if (name === 'recordings') refreshRecordings();
    if (name === 'device' && connected() && !state.configLoaded) readConfig();
    state.dirty = true;
  }
  qsa('.tabs button').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));

  // ---- status -----------------------------------------------------------------------
  function onStatus(st) {
    const prev = state.status;
    state.status = st;
    const pill = $('status-pill');
    const conn = st.connection;
    let text, s = st.state;
    if (!state.online) { s = 'offline'; text = 'Engine offline'; }
    else if (!conn) text = 'Not connected — click to connect';
    else {
      const addr = conn.protocol === 'modbus' || conn.protocol === 'simulated' ? ` · ${hex2(conn.address)}` : '';
      text = `${conn.port} · ${conn.baudrate}${addr} · ${st.state === 'connected' ? st.measured_hz.toFixed(1) + ' Hz' : 'no response'}`;
    }
    if (st.busy) text += ` · ${st.busy.replace(/_/g, ' ')}…`;
    pill.dataset.state = s;
    $('status-text').textContent = text;

    const rec = st.recording || {};
    const recBtn = $('btn-record');
    recBtn.disabled = !conn && !rec.active;
    recBtn.classList.toggle('on', !!rec.active);
    recBtn.lastElementChild.textContent = rec.active ? `${rec.rows.toLocaleString()} rows` : 'Record';
    $('btn-rec-start').disabled = !conn || rec.active;
    $('btn-rec-stop').disabled = !rec.active;
    $('rec-status').textContent = rec.active
      ? `Recording to ${rec.file} — ${rec.rows.toLocaleString()} rows, ${Math.round(rec.duration || 0)} s`
      : rec.file ? `Last file: ${rec.file} (${rec.rows.toLocaleString()} rows)` : 'Not recording.';
    if (prev && prev.recording && prev.recording.active && !rec.active && state.view === 'recordings') refreshRecordings();

    $('di-conn').textContent = conn ? `${conn.port} @ ${conn.baudrate} baud, ${conn.protocol}${conn.protocol !== 'standard' ? ', address ' + hex2(conn.address) : ''}` : 'not connected';
    if (document.activeElement !== $('set-rate')) $('set-rate').value = st.rate_hz;
    const wasConnected = prev && prev.connection;
    if (conn && !wasConnected) { state.configLoaded = false; if (state.view === 'device') readConfig(); }
    if (!conn) state.configLoaded = false;
  }

  // ---- samples ------------------------------------------------------------------------
  function onSample(s) {
    state.sample = s;
    const a = displayAngles(s);
    hist.push(s.t, {
      roll: a.roll, pitch: a.pitch, yaw: a.yaw,
      ax: s.acc[0], ay: s.acc[1], az: s.acc[2], an: s.acc_norm,
      gx: s.gyro[0], gy: s.gyro[1], gz: s.gyro[2],
      hx: s.mag[0], hy: s.mag[1], hz: s.mag[2],
    });
    if (state.magCal) mag.add(s.mag);
    state.dirty = true;
  }

  // ---- render loop ------------------------------------------------------------------
  function setText(id, v) { const el = $(id); if (el.textContent !== v) el.textContent = v; }

  function renderDashboard() {
    const s = state.sample;
    const a = displayAngles(s);
    setText('ro-roll', a ? f(a.roll, 2) : '—');
    setText('ro-pitch', a ? f(a.pitch, 2) : '—');
    setText('ro-yaw', a ? f(a.yaw, 2) : '—');
    setText('ro-tilt', a ? f(a.tilt, 2) : '—');
    setText('ro-temp', s ? f(s.temperature, 2) : '—');
    if (s) {
      setText('v-ax', f(s.acc[0], 4)); setText('v-ay', f(s.acc[1], 4)); setText('v-az', f(s.acc[2], 4)); setText('v-an', f(s.acc_norm, 4));
      setText('v-gx', f(s.gyro[0], 2)); setText('v-gy', f(s.gyro[1], 2)); setText('v-gz', f(s.gyro[2], 2));
      setText('v-hx', String(s.mag[0])); setText('v-hy', String(s.mag[1])); setText('v-hz', String(s.mag[2])); setText('v-hn', f(s.mag_norm, 0));
      ['q0', 'q1', 'q2', 'q3'].forEach((k, i) => setText('v-' + k, f(s.quaternion[i], 4)));
    }
    level.draw(a ? a.roll : null, a ? a.pitch : null, a ? a.tilt : 0);
    cube.draw(a ? a.roll : null, a ? a.pitch : null, a ? a.yaw : null);
    dial.draw(a ? a.yaw : null);
    chart.window = state.chartWindow;
    chart.draw(hist, state.paused);
    renderLegend();
  }

  function renderLegend() {
    const set = CHART_SETS[state.chartSet];
    const s = state.sample;
    const a = displayAngles(s);
    const val = (key) => {
      if (!s) return '—';
      const m = { roll: a.roll, pitch: a.pitch, yaw: a.yaw, ax: s.acc[0], ay: s.acc[1], az: s.acc[2], gx: s.gyro[0], gy: s.gyro[1], gz: s.gyro[2], hx: s.mag[0], hy: s.mag[1], hz: s.mag[2] };
      const d = state.chartSet === 'acc' ? 4 : state.chartSet === 'mag' ? 0 : 2;
      return f(m[key], d);
    };
    const html = set.series.map(([key, label, color]) =>
      `<span><i class="${color.slice(2)}"></i>${label} ${val(key)} ${set.unit}</span>`).join('');
    const el = $('legend-a');
    if (el.innerHTML !== html) el.innerHTML = html;
  }

  function renderDevice() {
    const s = state.sample;
    setText('di-clock', s && s.chip_time ? s.chip_time : '—');
    if (state.magCal || !state.magDrawn) {
      mag.draw();
      state.magDrawn = true;
      setText('mag-count', mag.pts.length ? `${mag.pts.length} points` : '');
    }
  }

  function frame() {
    if (state.dirty) {
      state.dirty = false;
      if (state.view === 'dashboard') renderDashboard();
      else if (state.view === 'device') renderDevice();
    }
    requestAnimationFrame(frame);
  }

  window.addEventListener('resize', () => { state.dirty = true; state.magDrawn = false; });
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { state.dirty = true; });
  }

  // ---- event stream ---------------------------------------------------------------------
  function openStream() {
    const es = new EventSource('/api/stream');
    es.addEventListener('open', () => { state.online = true; });
    es.addEventListener('status', (e) => { state.online = true; onStatus(JSON.parse(e.data)); });
    es.addEventListener('sample', (e) => onSample(JSON.parse(e.data)));
    es.addEventListener('error', () => {
      state.online = false;
      onStatus(state.status || { state: 'offline', connection: null, recording: {}, measured_hz: 0, rate_hz: 50 });
    });
  }

  // ---- chart controls --------------------------------------------------------------------
  function applyChartSet(name) {
    const set = CHART_SETS[name] || CHART_SETS.tilt;
    state.chartSet = name in CHART_SETS ? name : 'tilt';
    store.set('chartSet', state.chartSet);
    chart.configure({
      unit: set.unit, minSpan: set.minSpan,
      series: set.series.map(([key, label, color, wrap]) => ({ key, label, color: css(color), wrap: !!wrap })),
    });
    qsa('#chart-a-select button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.set === state.chartSet)));
    state.dirty = true;
  }
  qsa('#chart-a-select button').forEach((b) => b.addEventListener('click', () => applyChartSet(b.dataset.set)));
  qsa('#chart-window button').forEach((b) => b.addEventListener('click', () => {
    state.chartWindow = Number(b.dataset.win);
    store.set('chartWindow', state.chartWindow);
    qsa('#chart-window button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    state.dirty = true;
  }));
  qsa('#chart-window button').forEach((x) => x.setAttribute('aria-pressed', String(Number(x.dataset.win) === state.chartWindow)));
  $('btn-pause').addEventListener('click', () => {
    state.paused = state.paused == null ? hist.last() : null;
    $('btn-pause').textContent = state.paused == null ? 'Pause' : 'Resume';
    state.dirty = true;
  });
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => applyChartSet(state.chartSet));
  }

  // ---- tare ---------------------------------------------------------------------------------
  function renderTare() {
    $('btn-untare').hidden = !state.tare;
    $('tare-badge').hidden = !state.tare;
  }
  $('btn-tare').addEventListener('click', () => {
    const s = state.sample;
    if (!s) return toast('No data yet', 'error');
    state.tare = { roll: s.roll, pitch: s.pitch, yaw: s.yaw };
    store.set('tare', state.tare);
    hist.clear();
    renderTare(); state.dirty = true;
    toast('Display zeroed (sensor unchanged)');
  });
  $('btn-untare').addEventListener('click', () => {
    state.tare = null; store.set('tare', null); hist.clear(); renderTare(); state.dirty = true;
  });
  $('level-range').addEventListener('click', () => { $('level-range').textContent = `±${level.cycle()}°`; store.set('levelRange', level.range); state.dirty = true; });
  $('cv-level').addEventListener('click', () => $('level-range').click());

  // ---- connect dialog -------------------------------------------------------------------------
  const dlg = $('connect-dialog');

  async function loadPorts(selected) {
    const sel = $('c-port');
    try {
      const ports = await api('/api/ports');
      sel.innerHTML = '';
      for (const p of ports) {
        const o = document.createElement('option');
        o.value = p.device;
        o.textContent = `${p.device} — ${p.description}${p.likely ? '  ★' : ''}`;
        sel.appendChild(o);
      }
      if (!ports.length) sel.innerHTML = '<option value="">No serial ports found</option>';
      const want = selected || (ports.find((p) => p.likely) || {}).device;
      if (want && ports.some((p) => p.device === want)) sel.value = want;
    } catch (e) { toast(e.message, 'error'); }
  }

  function fillBauds(sel, value) {
    const rates = (state.meta && state.meta.baud_rates) || [4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600];
    sel.innerHTML = rates.map((r) => `<option value="${r}">${r}</option>`).join('');
    sel.value = String(value || 115200);
  }

  async function openConnect() {
    $('connect-error').hidden = true;
    const conn = connected();
    let preset = conn;
    if (!preset) { try { preset = (await api('/api/settings')).last_connection; } catch { /* none */ } }
    preset = preset || { protocol: 'modbus', baudrate: 115200, address: 0x50 };
    $('c-protocol').value = preset.protocol || 'modbus';
    fillBauds($('c-baud'), preset.baudrate);
    $('c-address').value = hex2(preset.address ?? 0x50);
    $('c-rate').value = (state.status && state.status.rate_hz) || preset.rate_hz || 50;
    $('btn-disconnect').hidden = !conn;
    syncProtocolFields();
    dlg.showModal();
    loadPorts(preset.port);
  }
  function syncProtocolFields() {
    const p = $('c-protocol').value;
    $('c-port').disabled = p === 'simulated';
    $('c-address').disabled = p === 'standard';
    $('c-rate').disabled = p === 'standard';
  }
  $('c-protocol').addEventListener('change', syncProtocolFields);
  $('status-pill').addEventListener('click', openConnect);
  $('btn-connect-cancel').addEventListener('click', () => dlg.close());
  $('btn-ports-refresh').addEventListener('click', () => loadPorts($('c-port').value));

  $('btn-connect').addEventListener('click', () => withBusy($('btn-connect'), async () => {
    $('connect-error').hidden = true;
    const body = {
      port: $('c-port').value, protocol: $('c-protocol').value, baudrate: Number($('c-baud').value),
      address: parseNum($('c-address').value), rate_hz: Number($('c-rate').value) || 50,
    };
    if (body.protocol !== 'simulated' && !body.port) throw new Error('Pick a serial port');
    try {
      const st = await api('/api/connect', body);
      onStatus(st);
      dlg.close();
      hist.clear();
      toast(`Connected to ${st.connection.port}`, 'ok');
    } catch (e) {
      $('connect-error').textContent = e.message;
      $('connect-error').hidden = false;
    }
  }));
  $('btn-disconnect').addEventListener('click', () => withBusy($('btn-disconnect'), async () => {
    onStatus(await api('/api/disconnect', {}));
    dlg.close();
  }));

  $('btn-scan').addEventListener('click', () => withBusy($('btn-scan'), async () => {
    $('scan-status').textContent = 'Scanning USB-serial ports… (can take ~10 s per port)';
    const list = $('scan-results');
    list.innerHTML = '';
    try {
      const r = await api('/api/scan', {});
      $('scan-status').textContent = r.found.length
        ? `Found ${r.found.length} sensor${r.found.length > 1 ? 's' : ''}.`
        : `Nothing found on ${r.scanned.join(', ') || 'any port'}${r.skipped ? ` (${r.skipped} is in use by this console)` : ''}.`;
      for (const hit of r.found) {
        const li = document.createElement('li');
        const desc = `${hit.port} · ${hit.protocol} · ${hit.baudrate}${hit.address != null ? ' · ' + hex2(hit.address) : ''}`;
        li.innerHTML = `<span></span><button type="button" class="btn small primary">Use</button>`;
        li.firstChild.textContent = desc;
        li.lastChild.addEventListener('click', async () => {
          await loadPorts(hit.port);
          $('c-protocol').value = hit.protocol;
          $('c-baud').value = String(hit.baudrate);
          if (hit.address != null) $('c-address').value = hex2(hit.address);
          syncProtocolFields();
          $('btn-connect').click();
        });
        list.appendChild(li);
      }
    } catch (e) { $('scan-status').textContent = e.message; }
  }));

  // ---- recording ------------------------------------------------------------------------------
  async function startRecording() {
    const st = await api('/api/record/start', { name: $('rec-name').value.trim() || null });
    toast(`Recording to ${st.file}`, 'ok');
  }
  async function stopRecording() {
    const st = await api('/api/record/stop', {});
    toast(`Saved ${st.rows.toLocaleString()} rows to ${st.file}`, 'ok');
    refreshRecordings();
  }
  $('btn-record').addEventListener('click', () => withBusy(null, () =>
    state.status && state.status.recording && state.status.recording.active ? stopRecording() : startRecording()));
  $('btn-rec-start').addEventListener('click', () => withBusy($('btn-rec-start'), startRecording));
  $('btn-rec-stop').addEventListener('click', () => withBusy($('btn-rec-stop'), stopRecording));
  $('btn-rec-refresh').addEventListener('click', refreshRecordings);

  async function refreshRecordings() {
    try {
      const r = await api('/api/recordings');
      $('rec-dir').textContent = `Saved in ${r.directory}`;
      const body = $('rec-files');
      if (!r.files.length) { body.innerHTML = '<tr><td colspan="4" class="empty">No recordings yet.</td></tr>'; return; }
      body.innerHTML = '';
      for (const file of r.files) {
        const tr = document.createElement('tr');
        tr.innerHTML = '<td class="mono"></td><td class="num"></td><td></td><td><a>Download</a></td>';
        tr.children[0].textContent = file.name;
        tr.children[1].textContent = bytes(file.size);
        tr.children[2].textContent = new Date(file.modified * 1000).toLocaleString();
        const a = tr.querySelector('a');
        a.href = '/recordings/' + encodeURIComponent(file.name);
        a.setAttribute('download', file.name);
        body.appendChild(tr);
      }
    } catch (e) { toast(e.message, 'error'); }
  }

  // ---- device page --------------------------------------------------------------------------------
  function fillSelect(sel, options) {
    sel.innerHTML = Object.entries(options).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
  }

  async function readConfig() {
    if (!connected()) return;
    const btn = $('btn-read-config');
    await withBusy(btn, async () => {
      const r = (await api('/api/command', { action: 'read_config' })).result;
      state.configLoaded = true;
      setText('di-fw', r.firmware || '—');
      setText('di-bw', r.bandwidth_label || '—');
      setText('di-alg', r.algorithm_label || '—');
      setText('di-orient', r.orientation_label || '—');
      setText('di-range', [r.acc_range, r.gyro_range].filter(Boolean).join(', ') || '—');
      setText('di-ref', r.roll_reference != null ? `roll ${r.roll_reference.toFixed(3)}°, pitch ${r.pitch_reference.toFixed(3)}°` : '—');
      setText('di-delay', r.reply_delay_us != null ? `${r.reply_delay_us} µs` : '—');
      if (r.bandwidth != null) $('set-bandwidth').value = String(r.bandwidth);
      if (r.algorithm != null) $('set-algorithm').value = String(r.algorithm);
      if (r.orientation != null) $('set-orientation').value = String(r.orientation);
      if (r.baudrate) $('set-baud').value = String(r.baudrate);
      if (r.address != null) $('set-address').value = hex2(r.address);
    });
  }
  $('btn-read-config').addEventListener('click', readConfig);

  async function runCommand(action, params = {}, btn = null) {
    if (!connected()) { toast('Connect a sensor first', 'error'); return undefined; }
    return withBusy(btn, async () => {
      const r = await api('/api/command', { action, ...params });
      toast(`${action.replace(/_/g, ' ')}: done`, 'ok');
      return r;
    });
  }

  qsa('[data-apply]').forEach((btn) => btn.addEventListener('click', async () => {
    const src = $(btn.dataset.src);
    const value = btn.dataset.hex !== undefined ? parseNum(src.value) : Number(src.value);
    if (!isFinite(value)) return toast('Enter a valid value', 'error');
    if (btn.dataset.confirm && !confirm(btn.dataset.confirm)) return;
    const param = btn.dataset.param || 'value';
    const r = await runCommand(btn.dataset.apply, { [param]: value }, btn);
    if (r && btn.dataset.apply !== 'set_rate') readConfig();
  }));

  qsa('[data-cmd]').forEach((btn) => btn.addEventListener('click', async () => {
    if (btn.dataset.confirm && !confirm(btn.dataset.confirm)) return;
    const r = await runCommand(btn.dataset.cmd, {}, btn);
    if (r && /reference|factory/.test(btn.dataset.cmd)) readConfig();
  }));

  $('btn-sync-clock').addEventListener('click', async () => {
    const r = await runCommand('sync_clock', {}, null);
    if (r) toast(`Sensor clock set to ${r.result}`, 'ok');
  });

  $('btn-cal-acc').addEventListener('click', async () => {
    if (!confirm('Accelerometer calibration: place the sensor level and keep it completely still for about 5 seconds. Start?')) return;
    await runCommand('calibrate_accel', { seconds: 5 }, $('btn-cal-acc'));
  });

  $('btn-mag-start').addEventListener('click', async () => {
    const r = await runCommand('mag_start', {}, $('btn-mag-start'));
    if (!r) return;
    state.magCal = true;
    mag.reset();
    $('btn-mag-start').disabled = true;
    $('btn-mag-stop').disabled = false;
    $('mag-hint').textContent = 'Calibrating… rotate slowly a full turn around X, then Y, then Z. Press Finish when done.';
  });
  $('btn-mag-stop').addEventListener('click', async () => {
    const r = await runCommand('mag_stop', {}, $('btn-mag-stop'));
    if (!r) return;
    state.magCal = false;
    $('btn-mag-start').disabled = false;
    $('btn-mag-stop').disabled = true;
    $('mag-hint').textContent = `Calibration saved (${mag.pts.length} samples collected). Press Start to run it again.`;
  });

  // ---- registers page --------------------------------------------------------------------------------
  let regTimer = null;
  function regRow(r) {
    const tr = document.createElement('tr');
    tr.dataset.addr = r.addr;
    tr.innerHTML = '<td class="mono"></td><td></td><td></td><td class="num"></td><td class="mono"></td><td class="num"></td><td></td><td></td>';
    tr.children[0].textContent = hex2(r.addr);
    tr.children[1].textContent = r.name;
    tr.children[2].textContent = r.label;
    if (r.writable) {
      const wrap = document.createElement('div');
      wrap.className = 'write';
      wrap.innerHTML = '<input spellcheck="false" aria-label="New value"><button class="btn">Write</button>';
      wrap.lastChild.addEventListener('click', () => writeRegister(r.addr, wrap.firstChild, wrap.lastChild));
      wrap.firstChild.addEventListener('keydown', (e) => { if (e.key === 'Enter') wrap.lastChild.click(); });
      tr.children[7].appendChild(wrap);
    }
    return tr;
  }
  function updateRegRow(tr, r) {
    const changed = tr.children[3].textContent !== String(r.raw);
    tr.children[3].textContent = String(r.raw);
    tr.children[4].textContent = r.hex;
    tr.children[5].textContent = r.value == null ? '' : `${r.value} ${r.unit}`.trim();
    tr.children[6].textContent = r.text || '';
    if (changed && tr.dataset.seen) { tr.classList.remove('changed'); void tr.offsetWidth; tr.classList.add('changed'); }
    tr.dataset.seen = '1';
  }
  function renderRegisters(rows) {
    const body = $('reg-body');
    if (!body.querySelector('tr[data-addr]')) body.innerHTML = '';
    for (const r of rows) {
      state.regs.set(r.addr, r);
      let tr = body.querySelector(`tr[data-addr="${r.addr}"]`);
      if (!tr) { tr = regRow(r); body.appendChild(tr); }
      updateRegRow(tr, r);
    }
    applyRegFilter();
  }
  function applyRegFilter() {
    const q = $('reg-filter').value.trim().toLowerCase();
    qsa('#reg-body tr[data-addr]').forEach((tr) => {
      tr.hidden = q && !tr.textContent.toLowerCase().includes(q);
    });
  }
  $('reg-filter').addEventListener('input', applyRegFilter);

  async function readAllRegisters(btn) {
    if (!connected()) { toast('Connect a sensor first', 'error'); return; }
    await withBusy(btn, async () => {
      const r = await api('/api/command', { action: 'read_registers', start: 0, count: 0x85 });
      renderRegisters(r.result);
    });
  }
  $('btn-reg-read').addEventListener('click', () => readAllRegisters($('btn-reg-read')));
  $('reg-auto').addEventListener('change', () => {
    clearInterval(regTimer);
    if ($('reg-auto').checked) {
      regTimer = setInterval(async () => {
        if (state.view !== 'registers' || !connected() || (state.status && state.status.busy)) return;
        try { renderRegisters((await api('/api/command', { action: 'read_registers', start: 0, count: 0x85 })).result); }
        catch { /* transient */ }
      }, 1000);
    }
  });

  async function writeRegister(addr, input, btn) {
    const value = parseNum(input.value);
    if (!Number.isInteger(value) || value < -32768 || value > 65535) return toast('Enter a 16-bit integer (decimal or 0x hex)', 'error');
    const save = $('reg-save').checked;
    const meta = state.regs.get(addr);
    if (!confirm(`Write ${value} to ${hex2(addr)} (${meta ? meta.label : 'register'})${save ? ' and save to flash' : ''}?`)) return;
    const r = await runCommand('write_register', { addr, value, save }, btn);
    if (r) {
      input.value = '';
      const rb = r.result.readback;
      toast(`${hex2(addr)} ← ${value}${rb != null ? ` (reads back ${rb})` : ''}`, 'ok');
      try { renderRegisters((await api('/api/command', { action: 'read_registers', start: addr, count: 1 })).result); } catch { /* ignore */ }
    }
  }

  // ---- boot ------------------------------------------------------------------------------------------------
  async function boot() {
    try {
      state.meta = await api('/api/meta');
      fillSelect($('set-bandwidth'), state.meta.bandwidths);
      fillSelect($('set-algorithm'), state.meta.algorithms);
      fillSelect($('set-orientation'), state.meta.orientations);
      fillBauds($('set-baud'), 115200);
    } catch (e) { toast('Engine not reachable: ' + e.message, 'error'); }
    $('level-range').textContent = `±${level.range}°`;
    applyChartSet(state.chartSet);
    renderTare();
    showView(state.view);
    openStream();
    requestAnimationFrame(frame);
    try {
      const st = await api('/api/status');
      state.online = true;
      onStatus(st);
      if (!st.connection) openConnect();
    } catch { /* stream error handler covers it */ }
  }
  boot();
})();
