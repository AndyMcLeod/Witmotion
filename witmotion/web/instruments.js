/* Canvas instruments for the WitMotion console: level, 3D box, yaw dial,
 * rolling chart, magnetometer scatter. No dependencies. */
(function (global) {
  'use strict';

  // ---- theme ---------------------------------------------------------------
  let palette = null;
  const TOKENS = ['bg', 'panel', 'panel-2', 'border', 'text', 'muted', 'faint', 'accent',
    'ok', 'warn', 'bad', 'x', 'y', 'z', 'grid', 'mono'];
  function colors() {
    if (!palette) {
      const s = getComputedStyle(document.documentElement);
      palette = {};
      for (const t of TOKENS) palette[t.replace('-', '')] = s.getPropertyValue('--' + t).trim();
    }
    return palette;
  }
  function invalidatePalette() { palette = null; }
  if (global.matchMedia) {
    global.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', invalidatePalette);
  }

  function fit(canvas) {
    const dpr = global.devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width));
    const h = Math.max(1, Math.round(r.height));
    const bw = Math.round(w * dpr), bh = Math.round(h * dpr);
    if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    return { ctx, w, h };
  }

  function alpha(color, a) {
    // works for #rrggbb tokens
    if (/^#[0-9a-f]{6}$/i.test(color)) {
      const n = parseInt(color.slice(1), 16);
      return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
    }
    return color;
  }

  const D2R = Math.PI / 180;
  const fmtDeg = (v) => (Math.abs(v) < 10 && v % 1 ? v.toFixed(1) : String(Math.round(v)));

  // ---- bubble level --------------------------------------------------------
  const RINGS = {
    1: [0.25, 0.5, 0.75, 1], 2: [0.5, 1, 1.5, 2], 5: [1, 2, 3, 4, 5],
    15: [5, 10, 15], 45: [15, 30, 45], 90: [30, 60, 90],
  };
  class Level {
    constructor(canvas) {
      this.canvas = canvas;
      this.ranges = [1, 2, 5, 15, 45, 90];
      this.range = 5;
    }
    cycle() {
      const i = this.ranges.indexOf(this.range);
      this.range = this.ranges[(i + 1) % this.ranges.length];
      return this.range;
    }
    draw(roll, pitch, tilt) {
      const { ctx, w, h } = fit(this.canvas);
      const c = colors();
      const cx = w / 2, cy = h / 2;
      const R = Math.min(w, h) / 2 - 12;
      if (R < 20) return;

      ctx.fillStyle = c.panel2;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.fill();

      ctx.lineWidth = 1;
      ctx.font = `10px ${c.mono}`;
      ctx.textBaseline = 'middle';
      const rings = RINGS[this.range] || [this.range / 2, this.range];
      for (const deg of rings) {
        const r = (R * deg) / this.range;
        ctx.strokeStyle = deg === this.range ? c.faint : c.border;
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.stroke();
        ctx.fillStyle = c.faint;
        ctx.fillText(fmtDeg(deg) + '°', cx + r * 0.71 + 3, cy - r * 0.71 - 4);
      }
      ctx.strokeStyle = c.border;
      ctx.beginPath();
      ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy);
      ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R);
      ctx.stroke();

      ctx.font = `600 11px ${c.mono}`;
      ctx.fillStyle = c.x; ctx.textAlign = 'right'; ctx.fillText('+X', cx + R - 4, cy + 10);
      ctx.fillStyle = c.y; ctx.textAlign = 'left'; ctx.fillText('+Y', cx + 6, cy - R + 10);
      ctx.textAlign = 'start';

      if (roll == null) return;
      // Bubble floats to the high side: +X raised -> ax>0 ~ -pitch; +Y raised -> ay>0 ~ roll.
      const k = R / this.range;
      const br = Math.max(8, R * 0.11);
      let px = -pitch * k, py = -roll * k;
      const d = Math.hypot(px, py), maxd = R - br - 2;
      const pinned = d > maxd;
      if (pinned) { px *= maxd / d; py *= maxd / d; }
      const col = pinned ? c.bad : tilt < 0.5 ? c.ok : tilt < 2 ? c.warn : c.accent;

      ctx.strokeStyle = c.faint;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.arc(cx, cy, br + 2, 0, 2 * Math.PI); ctx.stroke();
      ctx.setLineDash([]);

      const g = ctx.createRadialGradient(cx + px - br * 0.35, cy + py - br * 0.35, br * 0.1, cx + px, cy + py, br);
      g.addColorStop(0, alpha(col, 0.35));
      g.addColorStop(1, alpha(col, 0.85));
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx + px, cy + py, br, 0, 2 * Math.PI); ctx.fill();
      ctx.lineWidth = 1.5; ctx.strokeStyle = col; ctx.stroke();
    }
  }

  // ---- 3D orientation --------------------------------------------------------
  function rotZYX(roll, pitch, yaw) {
    const [cr, sr] = [Math.cos(roll * D2R), Math.sin(roll * D2R)];
    const [cp, sp] = [Math.cos(pitch * D2R), Math.sin(pitch * D2R)];
    const [cy, sy] = [Math.cos(yaw * D2R), Math.sin(yaw * D2R)];
    // R = Rz(yaw) * Ry(pitch) * Rx(roll)   (body -> world)
    return [
      [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
      [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
      [-sp, cp * sr, cp * cr],
    ];
  }
  const mul = (M, v) => [
    M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2],
    M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2],
    M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2],
  ];

  class Cube {
    constructor(canvas) {
      this.canvas = canvas;
      // WT901C housing is roughly 51 x 36 x 15 mm
      this.half = [0.51, 0.36, 0.15];
      this.az = -32 * D2R;
      this.el = 24 * D2R;
      this.f = 6;
    }
    view(p) {
      const ca = Math.cos(this.az), sa = Math.sin(this.az);
      const ce = Math.cos(this.el), se = Math.sin(this.el);
      const x1 = p[0] * ca - p[1] * sa;
      const y1 = p[0] * sa + p[1] * ca;
      const z1 = p[2];
      return [x1, z1 * ce + y1 * se, y1 * ce - z1 * se]; // [right, up, depth]
    }
    draw(roll, pitch, yaw) {
      const { ctx, w, h } = fit(this.canvas);
      const c = colors();
      const cx = w / 2, cy = h / 2 + 4;
      const S = Math.min(w, h) * 0.62;
      const proj = (v) => {
        const s = (this.f / (this.f + v[2])) * S;
        return [cx + v[0] * s, cy - v[1] * s];
      };

      // horizon ring (world XY plane)
      ctx.strokeStyle = c.border; ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i <= 72; i++) {
        const a = (i / 72) * 2 * Math.PI;
        const p = proj(this.view([0.82 * Math.cos(a), 0.82 * Math.sin(a), 0]));
        i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]);
      }
      ctx.stroke();

      if (roll == null) return;
      const R = rotZYX(roll, pitch, yaw);
      const [a, b, d] = this.half;
      const corner = (sx, sy, sz) => this.view(mul(R, [sx * a, sy * b, sz * d]));
      const faces = [
        { n: [1, 0, 0], v: [[1, -1, -1], [1, 1, -1], [1, 1, 1], [1, -1, 1]], tone: 'x' },
        { n: [-1, 0, 0], v: [[-1, -1, -1], [-1, -1, 1], [-1, 1, 1], [-1, 1, -1]], tone: 'side' },
        { n: [0, 1, 0], v: [[-1, 1, -1], [-1, 1, 1], [1, 1, 1], [1, 1, -1]], tone: 'side' },
        { n: [0, -1, 0], v: [[-1, -1, -1], [1, -1, -1], [1, -1, 1], [-1, -1, 1]], tone: 'side' },
        { n: [0, 0, 1], v: [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], tone: 'top' },
        { n: [0, 0, -1], v: [[-1, -1, -1], [-1, 1, -1], [1, 1, -1], [1, -1, -1]], tone: 'bottom' },
      ];
      const cam = [0, 0, -this.f];
      const light = [-0.35, 0.75, -0.55];
      const ln = Math.hypot(...light);
      const drawn = [];
      for (const f of faces) {
        const nv = this.view(mul(R, f.n));
        const pts = f.v.map((s) => corner(s[0], s[1], s[2]));
        const ctr = pts.reduce((acc, p) => [acc[0] + p[0] / 4, acc[1] + p[1] / 4, acc[2] + p[2] / 4], [0, 0, 0]);
        const toFace = [ctr[0] - cam[0], ctr[1] - cam[1], ctr[2] - cam[2]];
        if (nv[0] * toFace[0] + nv[1] * toFace[1] + nv[2] * toFace[2] >= 0) continue;
        const shade = 0.55 + 0.45 * Math.max(0, -(nv[0] * light[0] + nv[1] * light[1] + nv[2] * light[2]) / ln);
        drawn.push({ f, pts, shade, depth: ctr[2] });
      }
      drawn.sort((p, q) => q.depth - p.depth);
      for (const { f, pts, shade } of drawn) {
        const base = f.tone === 'top' ? c.accent : f.tone === 'x' ? c.x : f.tone === 'bottom' ? c.muted : c.faint;
        ctx.fillStyle = alpha(base, f.tone === 'side' ? 0.25 + 0.35 * shade : 0.35 + 0.55 * shade);
        ctx.strokeStyle = alpha(c.text, 0.55);
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        pts.forEach((p, i) => { const s = proj(p); i ? ctx.lineTo(s[0], s[1]) : ctx.moveTo(s[0], s[1]); });
        ctx.closePath(); ctx.fill(); ctx.stroke();
        if (f.tone === 'top') {
          // arrow on the lid pointing along +X
          const arrow = [[-0.25, 0], [0.28, 0], [0.16, 0.09], [0.28, 0], [0.16, -0.09]];
          ctx.strokeStyle = alpha(c.text, 0.8); ctx.lineWidth = 2;
          ctx.beginPath();
          arrow.forEach((q, i) => {
            const s = proj(this.view(mul(R, [q[0], q[1], d + 0.001])));
            i ? ctx.lineTo(s[0], s[1]) : ctx.moveTo(s[0], s[1]);
          });
          ctx.stroke();
        }
      }

      // body axes
      const o = proj(this.view([0, 0, 0]));
      const axes = [[[0.85, 0, 0], c.x, 'X'], [[0, 0.7, 0], c.y, 'Y'], [[0, 0, 0.55], c.z, 'Z']];
      ctx.font = `600 11px ${c.mono}`;
      for (const [v, col, label] of axes) {
        const p = proj(this.view(mul(R, v)));
        ctx.strokeStyle = col; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(p[0], p[1]); ctx.stroke();
        ctx.fillStyle = col;
        ctx.beginPath(); ctx.arc(p[0], p[1], 2.5, 0, 2 * Math.PI); ctx.fill();
        ctx.fillText(label, p[0] + 5, p[1] - 5);
      }
    }
  }

  // ---- yaw dial --------------------------------------------------------------
  class Dial {
    constructor(canvas) { this.canvas = canvas; }
    draw(yaw) {
      const { ctx, w, h } = fit(this.canvas);
      const c = colors();
      const cx = w / 2, cy = h / 2;
      const R = Math.min(w, h) / 2 - 10;
      if (R < 20) return;
      // value v (deg, CCW positive as seen from above) -> canvas angle
      const ang = (v) => (-90 - v) * D2R;

      ctx.fillStyle = c.panel2;
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.fill();
      ctx.strokeStyle = c.faint; ctx.lineWidth = 1; ctx.stroke();

      ctx.font = `10px ${c.mono}`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (let v = 0; v < 360; v += 5) {
        const a = ang(v);
        const major = v % 30 === 0;
        const r1 = R - (major ? 10 : v % 10 === 0 ? 6 : 3);
        ctx.strokeStyle = major ? c.muted : c.faint;
        ctx.lineWidth = major ? 1.5 : 1;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R);
        ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
        ctx.stroke();
        if (major) {
          const label = v > 180 ? v - 360 : v;
          ctx.fillStyle = v === 0 ? c.text : c.faint;
          ctx.fillText(String(label), cx + Math.cos(a) * (R - 22), cy + Math.sin(a) * (R - 22));
        }
      }
      if (yaw == null) { ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic'; return; }

      const a = ang(yaw);
      const tip = [cx + Math.cos(a) * (R - 30), cy + Math.sin(a) * (R - 30)];
      const tail = [cx - Math.cos(a) * (R * 0.25), cy - Math.sin(a) * (R * 0.25)];
      const perp = [Math.cos(a + Math.PI / 2) * 6, Math.sin(a + Math.PI / 2) * 6];
      ctx.fillStyle = c.z;
      ctx.beginPath();
      ctx.moveTo(tip[0], tip[1]);
      ctx.lineTo(cx + perp[0], cy + perp[1]);
      ctx.lineTo(tail[0], tail[1]);
      ctx.lineTo(cx - perp[0], cy - perp[1]);
      ctx.closePath(); ctx.fill();
      ctx.fillStyle = c.panel;
      ctx.beginPath(); ctx.arc(cx, cy, 3, 0, 2 * Math.PI); ctx.fill();

      ctx.fillStyle = c.text;
      ctx.font = `600 13px ${c.mono}`;
      ctx.fillText(`${yaw.toFixed(1)}°`, cx, cy + R * 0.42);
      ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
    }
  }

  // ---- history + chart -----------------------------------------------------
  class History {
    constructor(capacity, fields) {
      this.cap = capacity;
      this.t = new Float64Array(capacity);
      this.cols = {};
      for (const f of fields) this.cols[f] = new Float32Array(capacity);
      this.start = 0;
      this.len = 0;
    }
    clear() { this.start = 0; this.len = 0; }
    push(t, values) {
      const i = (this.start + this.len) % this.cap;
      if (this.len === this.cap) this.start = (this.start + 1) % this.cap; else this.len++;
      this.t[i] = t;
      for (const k in this.cols) this.cols[k][i] = values[k] ?? NaN;
    }
    last() { return this.len ? this.t[(this.start + this.len - 1) % this.cap] : null; }
    // index of the first sample with t >= tmin (binary search over the ring)
    firstSince(tmin) {
      let lo = 0, hi = this.len;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (this.t[(this.start + mid) % this.cap] < tmin) lo = mid + 1; else hi = mid;
      }
      return lo;
    }
  }

  function niceStep(span, target) {
    const raw = span / Math.max(1, target);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const n = raw / mag;
    return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
  }

  class Chart {
    constructor(canvas) {
      this.canvas = canvas;
      this.window = 30;
      this.series = [];
      this.unit = '';
      this.minSpan = 1;
    }
    configure({ series, unit, minSpan }) {
      this.series = series; this.unit = unit || ''; this.minSpan = minSpan || 1;
    }
    draw(hist, tEnd) {
      const { ctx, w, h } = fit(this.canvas);
      const c = colors();
      const L = 56, Rm = 12, T = 10, B = 24;
      const pw = w - L - Rm, ph = h - T - B;
      if (pw < 20 || ph < 20) return;
      const tmax = tEnd ?? hist.last();
      ctx.font = `11px ${c.mono}`;
      if (tmax == null) {
        ctx.fillStyle = c.faint; ctx.textAlign = 'center';
        ctx.fillText('waiting for data…', L + pw / 2, T + ph / 2);
        ctx.textAlign = 'start';
        return;
      }
      const tmin = tmax - this.window;
      const i0 = hist.firstSince(tmin);
      let lo = Infinity, hi = -Infinity;
      for (let k = i0; k < hist.len; k++) {
        const idx = (hist.start + k) % hist.cap;
        if (hist.t[idx] > tmax) break;
        for (const s of this.series) {
          const v = hist.cols[s.key][idx];
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
      if (!isFinite(lo)) { lo = -1; hi = 1; }
      if (hi - lo < this.minSpan) { const m = (hi + lo) / 2; lo = m - this.minSpan / 2; hi = m + this.minSpan / 2; }
      const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
      const ystep = niceStep(hi - lo, Math.max(3, Math.floor(ph / 45)));
      const X = (t) => L + ((t - tmin) / this.window) * pw;
      const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * ph;

      // grid
      ctx.strokeStyle = c.grid; ctx.lineWidth = 1; ctx.fillStyle = c.faint;
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      const dec = Math.max(0, -Math.floor(Math.log10(ystep)));
      for (let v = Math.ceil(lo / ystep) * ystep; v <= hi; v += ystep) {
        const y = Math.round(Y(v)) + 0.5;
        ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(L + pw, y); ctx.stroke();
        ctx.fillText((Math.abs(v) < ystep / 2 ? 0 : v).toFixed(dec), L - 6, y);
      }
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      const tstep = niceStep(this.window, Math.max(3, Math.floor(pw / 90)));
      for (let s = 0; s <= this.window + 1e-9; s += tstep) {
        const x = Math.round(X(tmax - s)) + 0.5;
        ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, T + ph); ctx.stroke();
        ctx.fillText(s === 0 ? 'now' : `−${s >= 60 && s % 60 === 0 ? s / 60 + ' min' : s + ' s'}`, x, T + ph + 6);
      }
      ctx.save();
      ctx.translate(12, T + ph / 2); ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(this.unit, 0, 0);
      ctx.restore();
      if (lo < 0 && hi > 0) {
        ctx.strokeStyle = c.border;
        const y0 = Math.round(Y(0)) + 0.5;
        ctx.beginPath(); ctx.moveTo(L, y0); ctx.lineTo(L + pw, y0); ctx.stroke();
      }

      // series (min/max decimation per pixel column)
      ctx.save();
      ctx.beginPath(); ctx.rect(L, T, pw, ph); ctx.clip();
      ctx.lineWidth = 1.6; ctx.lineJoin = 'round';
      const n = hist.len - i0;
      const decimate = n > pw * 2;
      for (const s of this.series) {
        ctx.strokeStyle = s.color;
        ctx.beginPath();
        let started = false, prevV = null, col = -1, cmin = 0, cmax = 0, cfirst = 0, clast = 0;
        const flush = () => {
          if (col < 0) return;
          const x = L + col + 0.5;
          if (!started) { ctx.moveTo(x, Y(cfirst)); started = true; } else ctx.lineTo(x, Y(cfirst));
          ctx.lineTo(x, Y(cmin)); ctx.lineTo(x, Y(cmax)); ctx.lineTo(x, Y(clast));
        };
        for (let k = i0; k < hist.len; k++) {
          const idx = (hist.start + k) % hist.cap;
          const t = hist.t[idx];
          if (t > tmax) break;
          const v = hist.cols[s.key][idx];
          if (!isFinite(v)) continue;
          const wrap = s.wrap && prevV !== null && Math.abs(v - prevV) > 180;
          prevV = v;
          if (decimate) {
            const cc = Math.floor(((t - tmin) / this.window) * pw);
            if (wrap) { flush(); col = -1; started = false; }
            if (cc !== col) {
              flush(); col = cc; cmin = cmax = cfirst = clast = v;
            } else { if (v < cmin) cmin = v; if (v > cmax) cmax = v; clast = v; }
          } else {
            const x = X(t), y = Y(v);
            if (!started || wrap) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
          }
        }
        if (decimate) flush();
        ctx.stroke();
      }
      ctx.restore();
      ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
    }
  }

  // ---- magnetometer scatter -------------------------------------------------
  class MagScatter {
    constructor(canvas) { this.canvas = canvas; this.pts = []; }
    reset() { this.pts = []; }
    add(m) {
      this.pts.push(m);
      if (this.pts.length > 6000) this.pts.splice(0, this.pts.length - 6000);
    }
    draw() {
      const { ctx, w, h } = fit(this.canvas);
      const c = colors();
      const cx = w / 2, cy = h / 2;
      ctx.strokeStyle = c.border; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, cy + 0.5); ctx.lineTo(w, cy + 0.5); ctx.moveTo(cx + 0.5, 0); ctx.lineTo(cx + 0.5, h); ctx.stroke();
      if (!this.pts.length) {
        ctx.fillStyle = c.faint; ctx.font = `11px ${c.mono}`; ctx.textAlign = 'center';
        ctx.fillText('no samples yet', cx, cy - 10); ctx.textAlign = 'start';
        return;
      }
      const mins = [Infinity, Infinity, Infinity], maxs = [-Infinity, -Infinity, -Infinity];
      for (const p of this.pts) for (let i = 0; i < 3; i++) { if (p[i] < mins[i]) mins[i] = p[i]; if (p[i] > maxs[i]) maxs[i] = p[i]; }
      const mid = mins.map((m, i) => (m + maxs[i]) / 2);
      const ext = Math.max(1, ...maxs.map((m, i) => (m - mins[i]) / 2));
      const s = (Math.min(w, h) / 2 - 10) / ext;
      const pairs = [[0, 1, c.x], [1, 2, c.y], [0, 2, c.z]];
      for (const [i, j, col] of pairs) {
        ctx.fillStyle = alpha(col, 0.55);
        for (const p of this.pts) ctx.fillRect(cx + (p[i] - mid[i]) * s - 1, cy - (p[j] - mid[j]) * s - 1, 2, 2);
      }
    }
  }

  global.WitInstruments = { Level, Cube, Dial, Chart, History, MagScatter, invalidatePalette };
})(window);
