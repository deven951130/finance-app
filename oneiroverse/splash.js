// Oneiroverse 開啟畫面（所有 Oneiroverse 軟體共用，正本在 OneiHub/brand-kit/，改完用 sync.ps1 複製到各 App）。
//
// 用法一：<body> 的第一個元素放 <script src=".../splash.js"></script>，載入時自動在整個視窗上播一次。
//   同資料夾要有 crescent.png、o.png、wordmark.png、trail.png（source/hires/compose.py 產生）。
//   重新整理 / 上一頁不會再播。<script> 加 data-manual 就只載入不自動播。
// 用法二：OneiroverseSplash.play({ root, images, onDone })，在指定元素上播（打包工具 import 進來時用這個）。
//   images 是 { crescent, o, wordmark, trail } 四張圖的網址；沒給時用 splash.js 同資料夾的檔案。
// 點一下或按任意鍵可跳過；系統設定「減少動態效果」時只淡入淡出。
//
// 動畫照 2026-10-14 夢境前線的原版（使用者指定）：彎月沿著弧線一筆畫出、前端帶一點光 → O 放大浮現 →
// 字標、流星尾由左到右顯現 → 四顆星星一顆一顆閃，約 4.4 秒。全部畫在一張 canvas 上。
(() => {
  if (typeof window === "undefined" || window.OneiroverseSplash) return;
  const script = document.currentScript;
  // 內嵌在 HTML 裡的 <script>（沒有 src）沒有同資料夾可找，這時要用 play({ images }) 自己給圖
  const scriptBase = script?.src ? new URL(".", script.src).href : "";

  // ---------- Logo 的位置資料（座標都是 Logo 原圖 1152×922 上的像素，來自 source/hires/brand.json） ----------
  // 四張圖層都畫在原圖的 BOX 範圍（1512×1236 = BOX 放大 2 倍）；EXTENT 是每個圖層實際有內容的範圍。
  const BOX = [194, 174, 950, 792];
  // 月牙繞 (cx, cy) 從 start 逆時針畫 length 弧度；track 是 [走過的角度, 月牙中線的半徑]；
  // 星星是 [x, y, 半徑]；CONTENT 是整個 Logo 的範圍（用來置中、決定大小）
  const SWEEP = { cx: 582.0, cy: 353.5, start: 4.5727, length: 3.9328,
    track: [[0.0524, 170.8], [0.1047, 169.8], [0.1571, 168.4], [0.2094, 167.0], [0.2618, 165.7], [0.3142, 164.4], [0.3665,
      163.1], [0.4189, 162.0], [0.4712, 160.9], [0.5236, 159.7], [0.576, 158.7], [0.6283, 157.7], [0.6807, 156.7],
      [0.733, 155.8], [0.7854, 154.9], [0.8378, 154.1], [0.8901, 153.4], [0.9425, 152.8], [0.9948, 152.2], [1.0472,
      151.5], [1.0996, 151.2], [1.1519, 150.7], [1.2043, 150.3], [1.2566, 150.1], [1.309, 149.9], [1.3614, 149.7],
      [1.4137, 149.5], [1.4661, 149.6], [1.5184, 149.4], [1.5708, 149.5], [1.6232, 149.6], [1.6755, 149.7], [1.7279,
      149.9], [1.7802, 150.2], [1.8326, 150.5], [1.885, 150.8], [1.9373, 151.1], [1.9897, 151.6], [2.042, 152.0],
      [2.0944, 152.7], [2.1468, 153.3], [2.1991, 154.2], [2.2515, 154.7], [2.3038, 155.5], [2.3562, 156.3], [2.4086,
      157.3], [2.4609, 158.2], [2.5133, 159.1], [2.5656, 160.2], [2.618, 161.2], [2.6704, 162.4], [2.7227, 163.5],
      [2.7751, 164.7], [2.8274, 165.9], [2.8798, 167.1], [2.9322, 168.4], [2.9845, 170.0], [3.0369, 171.0], [3.0892,
      172.4], [3.1416, 173.8], [3.194, 175.2], [3.2463, 176.6], [3.2987, 178.0], [3.351, 179.4], [3.4034, 180.7],
      [3.4558, 182.1], [3.5081, 183.5], [3.5605, 184.8], [3.6128, 186.1], [3.6652, 187.3], [3.7176, 188.6], [3.7699,
      189.7], [3.8223, 191.0], [3.8746, 191.7]] };
  const SPARKLES = [[801, 741, 29], [843, 695, 15], [910, 690, 20], [866, 752, 15]];
  const EXTENT = {"crescent": [414, 178, 738, 542], "o": [506, 277, 658, 430], "wordmark": [214, 577, 908, 667], "trail": [684, 667, 938, 778]};
  const CONTENT = [222, 185, 930, 770];

  const LAYERS = ["crescent", "o", "wordmark", "trail"];
  // 時間軸（秒）
  const FULL = { crescent: [0.3, 1.4], o: [0.9, 1.7], word: [1.4, 2.4], trail: [2.1, 2.9], logoOut: [3.6, 4.0] };
  const SPARKLE_START = 2.4, SPARKLE_STEP = 0.15, SPARKLE_LEN = 0.6; // 星星一顆接一顆，各閃 0.6 秒
  const END = 3.9; // 這時開始整個畫面淡出（.7 秒）
  // 減少動態效果：整個 Logo 淡入淡出，不畫弧線、不閃星星
  const REDUCED = { logoIn: [0.2, 0.6], logoOut: [1.8, 2.1] };
  const END_REDUCED = 2.0;
  // 月牙掃描前端的柔邊（弧度）、字標和流星尾顯現的柔邊（原圖像素）
  const SWEEP_FEATHER = 0.35, WORD_FEATHER = 60, TRAIL_FEATHER = 40;

  const CSS = `
html.ov-lock { overflow: hidden; }
.ov-splash { position: absolute; inset: 0; z-index: 2147483647; overflow: hidden;
  cursor: pointer; touch-action: none; user-select: none; -webkit-user-select: none; transition: opacity .7s ease;
  background: radial-gradient(ellipse 45% 40% at 80% 20%, rgba(123, 92, 240, .06), transparent 70%),
              radial-gradient(ellipse 45% 40% at 15% 85%, rgba(59, 227, 224, .07), transparent 70%),
              radial-gradient(ellipse 75% 65% at 50% 46%, #f4f9fc 0%, #f1f6fb 55%, #e7eff7 100%); }
.ov-splash.ov-fixed { position: fixed; }
.ov-splash.ov-out { opacity: 0; pointer-events: none; }
.ov-splash canvas { position: absolute; inset: 0; width: 100%; height: 100%; }`;
  // 修飾鍵和全螢幕鍵不算「跳過」
  const IGNORED_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "F11"]);
  let styleEl = null;
  let playing = 0;

  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  const span = (t, [a, b]) => clamp01((t - a) / (b - a));
  const easeOutCubic = (p) => 1 - (1 - p) ** 3;
  const easeInOutCubic = (p) => (p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2);
  const easeOutBack = (p) => 1 + 2.70158 * (p - 1) ** 3 + 1.70158 * (p - 1) ** 2;

  /** 開場第 t 秒的畫面狀態（只看時間，不碰畫面） */
  function state(t, reduced) {
    if (reduced) {
      return { logo: Math.min(span(t, REDUCED.logoIn), 1 - span(t, REDUCED.logoOut)),
        crescent: 1, o: 1, word: 1, trail: 1, sparkles: SPARKLES.map(() => 0) };
    }
    return {
      logo: 1 - span(t, FULL.logoOut),
      crescent: easeInOutCubic(span(t, FULL.crescent)),
      o: span(t, FULL.o),
      word: easeOutCubic(span(t, FULL.word)),
      trail: easeOutCubic(span(t, FULL.trail)),
      sparkles: SPARKLES.map((_, i) => {
        const a = SPARKLE_START + i * SPARKLE_STEP;
        const p = span(t, [a, a + SPARKLE_LEN]);
        return p > 0 && p < 1 ? Math.sin(p * Math.PI) : 0;
      }),
    };
  }

  /** 沿著月牙中線，走過 u 弧度時的半徑（track 之間線性內插） */
  function trackRadius(u) {
    const track = SWEEP.track;
    if (u <= track[0][0]) return track[0][1];
    for (let i = 1; i < track.length; i++) {
      const [u1, r1] = track[i];
      if (u <= u1) {
        const [u0, r0] = track[i - 1];
        return r0 + ((r1 - r0) * (u - u0)) / (u1 - u0);
      }
    }
    return track[track.length - 1][1];
  }

  /** 負責把 Logo 畫到 canvas 上。ctx 的座標系是 Logo 原圖的像素。 */
  function painter(canvas, imgs) {
    const ctx = canvas.getContext("2d");
    const work = document.createElement("canvas"); // 暫存畫布：做裁切（mask）用
    const wctx = work.getContext("2d");
    let m = [1, 0, 0, 1, 0, 0]; // 原圖座標 → 裝置像素

    // 把圖層裡 EXTENT 那一塊畫到原圖座標上（圖層本身是 BOX 範圍放大的圖）
    function place(c, name) {
      const img = imgs[name];
      const k = img.naturalWidth / (BOX[2] - BOX[0]);
      const [x0, y0, x1, y1] = EXTENT[name];
      c.drawImage(img, (x0 - BOX[0]) * k, (y0 - BOX[1]) * k, (x1 - x0) * k, (y1 - y0) * k, x0, y0, x1 - x0, y1 - y0);
    }

    /** 在暫存畫布上畫圖層，用 fill 做出的形狀裁切（destination-in），再貼回主畫布 */
    function masked(name, fill) {
      const [x0, y0, x1, y1] = EXTENT[name];
      wctx.setTransform(...m);
      wctx.globalCompositeOperation = "source-over";
      wctx.clearRect(x0 - 2, y0 - 2, x1 - x0 + 4, y1 - y0 + 4);
      place(wctx, name);
      wctx.globalCompositeOperation = "destination-in";
      wctx.fillStyle = fill(wctx);
      wctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      wctx.globalCompositeOperation = "source-over";
      const sx = Math.max(0, Math.floor(m[0] * x0 + m[4]) - 2);
      const sy = Math.max(0, Math.floor(m[3] * y0 + m[5]) - 2);
      const sw = Math.min(work.width - sx, Math.ceil(m[0] * (x1 - x0)) + 4);
      const sh = Math.min(work.height - sy, Math.ceil(m[3] * (y1 - y0)) + 4);
      if (sw <= 0 || sh <= 0) return;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(work, sx, sy, sw, sh, sx, sy, sw, sh);
      ctx.setTransform(...m);
    }

    /** 月牙從上方尖端逆時針、沿著弧線一筆畫出來，前端帶一點光 */
    function crescent(p) {
      if (p <= 0) return;
      if (p >= 1) return place(ctx, "crescent");
      const { cx, cy, start, length } = SWEEP;
      const tau = Math.PI * 2;
      const r = p * (length + SWEEP_FEATHER);
      masked("crescent", (c) => {
        // 錐形漸層從 start - r 順時針：先是柔邊，再到起點都不透明，起點之後透明
        const g = c.createConicGradient(start - r, cx, cy);
        g.addColorStop(0, "rgba(0,0,0,0)");
        g.addColorStop(Math.min(SWEEP_FEATHER, r) / tau, "#000");
        g.addColorStop(r / tau, "#000");
        g.addColorStop(Math.min(1, r / tau + 0.002), "rgba(0,0,0,0)");
        return g;
      });
      const u = Math.min(length, Math.max(0, r - SWEEP_FEATHER / 2));
      const a = start - u, rad = trackRadius(u);
      const x = cx + Math.cos(a) * rad, y = cy + Math.sin(a) * rad;
      const glow = ctx.createRadialGradient(x, y, 0, x, y, 24);
      glow.addColorStop(0, "rgba(255,255,255,0.95)");
      glow.addColorStop(0.35, "rgba(96,214,232,0.45)");
      glow.addColorStop(1, "rgba(96,214,232,0)");
      const alpha = ctx.globalAlpha;
      ctx.globalAlpha = alpha * Math.sin(p * Math.PI);
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(x, y, 24, 0, tau);
      ctx.fill();
      ctx.globalAlpha = alpha;
    }

    /** O 淡入，從 82% 放大並輕微回彈 */
    function o(p) {
      if (p <= 0) return;
      const [x0, y0, x1, y1] = EXTENT.o;
      const ox = (x0 + x1) / 2, oy = (y0 + y1) / 2, sc = 0.82 + 0.18 * easeOutBack(p);
      const alpha = ctx.globalAlpha;
      ctx.save();
      ctx.globalAlpha = alpha * easeOutCubic(p);
      ctx.translate(ox, oy);
      ctx.scale(sc, sc);
      ctx.translate(-ox, -oy);
      place(ctx, "o");
      ctx.restore();
    }

    /** 由左到右顯現，邊緣柔化 feather 像素 */
    function wipe(name, p, feather) {
      if (p <= 0) return;
      if (p >= 1) return place(ctx, name);
      const [x0, , x1] = EXTENT[name];
      const edge = x0 + (x1 - x0 + feather) * p;
      masked(name, (c) => {
        const g = c.createLinearGradient(edge - feather, 0, edge, 0);
        g.addColorStop(0, "#000");
        g.addColorStop(1, "rgba(0,0,0,0)");
        return g;
      });
    }

    /** 星星閃一下：淡紫光暈加白色四芒星 */
    function glint([x, y, r], g) {
      const alpha = ctx.globalAlpha;
      ctx.save();
      ctx.globalAlpha = alpha * g;
      const halo = ctx.createRadialGradient(x, y, 0, x, y, r * 2.2);
      halo.addColorStop(0, "rgba(255,255,255,0.9)");
      halo.addColorStop(0.3, "rgba(170,160,235,0.35)");
      halo.addColorStop(1, "rgba(170,160,235,0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(x, y, r * 2.2, 0, Math.PI * 2);
      ctx.fill();
      const len = r * (1.1 + 0.8 * g), waist = r * 0.12;
      ctx.translate(x, y);
      ctx.rotate(g * 0.4);
      ctx.fillStyle = "rgba(255,255,255,0.95)";
      ctx.beginPath();
      ctx.moveTo(0, -len);
      ctx.quadraticCurveTo(waist, -waist, len, 0);
      ctx.quadraticCurveTo(waist, waist, 0, len);
      ctx.quadraticCurveTo(-waist, waist, -len, 0);
      ctx.quadraticCurveTo(-waist, -waist, 0, -len);
      ctx.fill();
      ctx.restore();
    }

    return function draw(s, w, h, dpr, specks, t) {
      const cw = Math.max(1, Math.round(w * dpr)), ch = Math.max(1, Math.round(h * dpr));
      if (canvas.width !== cw || canvas.height !== ch) {
        canvas.width = work.width = cw;
        canvas.height = work.height = ch;
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = 1;
      ctx.clearRect(0, 0, cw, ch);
      // 背景的小光點：淡淡的品牌青、紫
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      for (const p of specks) {
        ctx.globalAlpha = p.a * (0.55 + 0.45 * Math.sin(t * p.s + p.p));
        ctx.fillStyle = p.c;
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, p.r, 0, 6.283);
        ctx.fill();
      }
      if (s.logo <= 0) return;
      // Logo 置中：寬不超過畫面 60%、高不超過 56%，也不放大到超過原圖 1.2 倍（圖層是 2 倍解析度，放太大會糊）
      const [x0, y0, x1, y1] = CONTENT;
      const k = Math.min((w * 0.6) / (x1 - x0), (h * 0.56) / (y1 - y0), 1.2);
      m = [dpr * k, 0, 0, dpr * k, dpr * (w / 2 - ((x0 + x1) / 2) * k), dpr * (h / 2 - ((y0 + y1) / 2) * k)];
      ctx.setTransform(...m);
      ctx.globalAlpha = s.logo;
      crescent(s.crescent);
      o(s.o);
      wipe("wordmark", s.word, WORD_FEATHER);
      wipe("trail", s.trail, TRAIL_FEATHER);
      SPARKLES.forEach((sp, i) => s.sparkles[i] > 0 && glint(sp, s.sparkles[i]));
      ctx.globalAlpha = 1;
    };
  }

  function play({ root = document.body, images = {}, onDone } = {}) {
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const whole = root === document.body;
    const src = (n) => images[n] || `${scriptBase}${n}.png`;
    if (!styleEl) {
      styleEl = document.createElement("style");
      styleEl.textContent = CSS;
      document.head.appendChild(styleEl);
    }
    playing++;

    const el = document.createElement("div");
    el.className = whole ? "ov-splash ov-fixed" : "ov-splash";
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", "Oneiroverse");
    const canvas = document.createElement("canvas");
    el.appendChild(canvas);
    root.prepend(el);
    if (whole) document.documentElement.classList.add("ov-lock"); // 動畫期間藏起底下頁面的捲軸

    let gone = false, raf = 0, timer = 0, t0 = -1;
    const cleanup = () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
      el.remove();
      if (--playing === 0 && styleEl) { styleEl.remove(); styleEl = null; }
    };
    const exit = (fast) => {
      if (gone) return;
      gone = true;
      clearTimeout(failsafe);
      el.removeEventListener("pointerdown", onPointer);
      removeEventListener("keydown", onKey, true);
      // 淡出一開始就還原捲軸：版面寬度的變化發生在動畫層還不透明的時候，看不到跳動。
      if (whole) document.documentElement.classList.remove("ov-lock");
      if (fast) el.style.transitionDuration = ".25s";
      el.classList.add("ov-out");
      setTimeout(() => { cleanup(); onDone?.(); }, fast ? 300 : 800);
    };
    // 點擊只用來跳過，不傳給底下的畫面（例如遊戲選單）
    const onPointer = (e) => { e.preventDefault(); e.stopPropagation(); exit(true); };
    // 按鍵也只用來跳過：在 window 的捕獲階段先攔下來，不會同時觸發底下畫面的快捷鍵
    const onKey = (e) => {
      if (IGNORED_KEYS.has(e.key)) return;
      e.preventDefault();
      e.stopPropagation();
      if (!e.repeat) exit(true);
    };
    el.addEventListener("pointerdown", onPointer);
    addEventListener("keydown", onKey, true);
    const failsafe = setTimeout(() => exit(true), 8000); // 圖片載入異常也不會一直擋住畫面

    const imgs = {};
    const loads = LAYERS.map((n) => {
      const img = new Image();
      img.src = src(n);
      imgs[n] = img;
      return img.decode();
    });
    const tints = ["#7fd8e6", "#a99be8", "#b9d4f0"];
    const W = el.clientWidth || innerWidth, H = el.clientHeight || innerHeight;
    const specks = Array.from({ length: Math.round((W * H) / 4500) }, () => ({
      x: Math.random(), y: Math.random(), r: Math.random() * 1.1 + 0.5, a: Math.random() * 0.5 + 0.2,
      p: Math.random() * 6.28, s: reduced ? 0 : Math.random() * 2 + 0.6, c: tints[Math.floor(Math.random() * tints.length)],
    }));

    Promise.all(loads).then(() => {
      if (gone) return;
      clearTimeout(failsafe);
      const draw = painter(canvas, imgs);
      const end = reduced ? END_REDUCED : END;
      const frame = (now) => {
        if (gone && !el.isConnected) return;
        raf = requestAnimationFrame(frame);
        // 時間從圖片載完後的第一幀開始算：視窗還沒顯示時不會先播掉
        if (t0 < 0) t0 = now;
        const t = (now - t0) / 1000;
        draw(state(t, reduced), el.clientWidth || innerWidth, el.clientHeight || innerHeight,
          Math.min(devicePixelRatio || 1, 2), specks, t);
        if (t >= end) exit();
      };
      raf = requestAnimationFrame(frame);
    }, () => exit(true)); // 圖片載不到：直接結束，不擋住畫面

    return {
      /** 淡出並結束（和使用者點一下一樣） */
      skip: () => exit(true),
      /** 立刻移除，不呼叫 onDone（畫面被銷毀時用） */
      destroy() {
        if (gone) return;
        gone = true;
        clearTimeout(failsafe);
        el.removeEventListener("pointerdown", onPointer);
        removeEventListener("keydown", onKey, true);
        if (whole) document.documentElement.classList.remove("ov-lock");
        cleanup();
      },
    };
  }

  window.OneiroverseSplash = { play };

  if (script && !script.hasAttribute("data-manual")) {
    const nav = performance.getEntriesByType?.("navigation")[0];
    if (!nav || (nav.type !== "reload" && nav.type !== "back_forward")) play();
  }
})();
