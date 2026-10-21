// Oneiroverse 開啟畫面（所有 Oneiroverse 軟體共用，正本在 OneiHub/brand-kit/，改完用 sync.ps1 複製到各 App）。
//
// 用法一：<body> 的第一個元素放 <script src=".../splash.js"></script>，載入時自動在整個視窗上播一次。
//   同資料夾要有 crescent.png、o.png、wordmark.png（source/make_splash.py 從 Logo 原圖產生）。
//   重新整理 / 上一頁不會再播。<script> 加 data-manual 就只載入不自動播。
// 用法二：OneiroverseSplash.play({ root, images, onDone })，在指定元素上播（打包工具 import 進來時用這個）。
//   images 是 { crescent, o, wordmark } 三張圖的網址；沒給時用 splash.js 同資料夾的檔案。
// 點一下或按任意鍵可跳過；系統設定「減少動態效果」時只淡入淡出。
(() => {
  if (typeof window === "undefined" || window.OneiroverseSplash) return;
  const script = document.currentScript;
  // 內嵌在 HTML 裡的 <script>（沒有 src）沒有同資料夾可找，這時要用 play({ images }) 自己給圖
  const scriptBase = script?.src ? new URL(".", script.src).href : "";
  // 淺色開啟畫面：圖層以 #f4f9fc 為底色做 color-to-alpha（source/make_splash.py），疊在這個顏色上才會和原圖一樣。
  const conic = "conic-gradient(from calc(352deg - var(--ov-sw)) at 51.1% 38.2%, transparent 0deg, #000 min(14deg, var(--ov-sw)), #000 var(--ov-sw), transparent var(--ov-sw))";
  const CSS = `
@property --ov-sw { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
html.ov-lock { overflow: hidden; }
.ov-splash { position: absolute; inset: 0; z-index: 2147483647; display: grid; place-items: center; overflow: hidden;
  cursor: pointer; touch-action: none; user-select: none; -webkit-user-select: none; transition: opacity .7s ease;
  background: radial-gradient(ellipse 45% 40% at 80% 20%, rgba(123, 92, 240, .06), transparent 70%),
              radial-gradient(ellipse 45% 40% at 15% 85%, rgba(59, 227, 224, .07), transparent 70%),
              radial-gradient(ellipse 75% 65% at 50% 46%, #f4f9fc 0%, #f1f6fb 55%, #e7eff7 100%); }
.ov-splash.ov-fixed { position: fixed; }
.ov-splash.ov-out { opacity: 0; pointer-events: none; }
.ov-splash .ov-stars { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; }
.ov-splash .ov-logo { position: relative; width: min(560px, 78%, calc(70cqh * 732 / 518)); aspect-ratio: 732 / 518;
  transition: transform .7s cubic-bezier(.4, 0, .2, 1); }
.ov-splash { container-type: size; }
.ov-splash.ov-out .ov-logo { transform: scale(1.05); }
.ov-splash .ov-logo > * { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; -webkit-user-drag: none; }
.ov-splash .ov-crescent { -webkit-mask-image: ${conic}; mask-image: ${conic}; }
.ov-splash .ov-crescent.ov-drawn { -webkit-mask-image: none; mask-image: none; }
.ov-splash .ov-o { transform-origin: 51.9% 34%; }
.ov-splash .ov-shine {
  background: linear-gradient(100deg, transparent 42%, rgba(160, 240, 240, .85) 50%, transparent 58%) 100% 0 / 300% 100% no-repeat;
  -webkit-mask: var(--ov-word) center / 100% 100% no-repeat; mask: var(--ov-word) center / 100% 100% no-repeat; }
.ov-splash.ov-play .ov-stars { animation: ov-fade 1.4s ease both; }
.ov-splash.ov-play .ov-crescent { animation: ov-fade .35s ease-out .15s both, ov-draw 1.3s cubic-bezier(.45, 0, .2, 1) .15s both,
  ov-pulse 1.1s ease-in-out 2.15s; }
.ov-splash.ov-play .ov-o { animation: ov-o 1s cubic-bezier(.2, .7, .2, 1) .95s both, ov-pulse 1.1s ease-in-out 2.15s; }
.ov-splash.ov-play .ov-word { animation: ov-word 1.1s cubic-bezier(.2, .7, .2, 1) 1.4s both; }
.ov-splash.ov-play .ov-shine { animation: ov-shine 1s ease-in-out 2.2s both; }
@keyframes ov-fade { from { opacity: 0 } to { opacity: 1 } }
@keyframes ov-draw { from { --ov-sw: 0deg } to { --ov-sw: 270deg } }
@keyframes ov-o { from { opacity: 0; transform: scale(.8); filter: blur(10px) saturate(1.6) }
  60% { opacity: 1; filter: blur(0) saturate(1.3) } to { opacity: 1; transform: none; filter: none } }
@keyframes ov-word { from { opacity: 0; clip-path: inset(0 50% 0 50%); filter: blur(6px); transform: translateY(8px) }
  to { opacity: 1; clip-path: inset(0); filter: none; transform: none } }
@keyframes ov-shine { from { opacity: 1; background-position: 100% 0 } to { opacity: 1; background-position: 0 0 } }
@keyframes ov-pulse { 50% { filter: saturate(1.4) brightness(1.08) } }
@media (prefers-reduced-motion: reduce) {
  .ov-splash .ov-crescent { -webkit-mask-image: none; mask-image: none; }
  .ov-splash.ov-play .ov-stars, .ov-splash.ov-play .ov-logo > :not(.ov-shine) { animation: ov-fade .4s ease both; }
  .ov-splash.ov-out .ov-logo { transform: none; }
}`;
  // 修飾鍵和全螢幕鍵不算「跳過」
  const IGNORED_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "F11"]);
  let styleEl = null;
  let playing = 0;

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
    el.innerHTML = `<canvas class="ov-stars"></canvas><div class="ov-logo">
      <img class="ov-crescent" alt="" src="${src("crescent")}"><img class="ov-o" alt="" src="${src("o")}">
      <img class="ov-word" alt="" src="${src("wordmark")}"><div class="ov-shine"></div></div>`;
    el.querySelector(".ov-shine").style.setProperty("--ov-word", `url("${src("wordmark")}")`);
    const crescent = el.querySelector(".ov-crescent");
    crescent.addEventListener("animationend", (e) => e.animationName === "ov-draw" && crescent.classList.add("ov-drawn"));
    root.prepend(el);
    if (whole) document.documentElement.classList.add("ov-lock"); // 動畫期間藏起底下頁面的捲軸

    let gone = false, raf = 0, timer = 0;
    const cleanup = () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
      el.remove();
      if (--playing === 0 && styleEl) { styleEl.remove(); styleEl = null; }
    };
    const exit = (fast) => {
      if (gone) return;
      gone = true;
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

    const canvas = el.querySelector("canvas"), ctx = canvas.getContext("2d");
    const W = el.clientWidth || innerWidth, H = el.clientHeight || innerHeight, dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);
    // 背景的小光點：淡淡的品牌青、紫，像原圖流星尾旁的星星
    const tints = ["#7fd8e6", "#a99be8", "#b9d4f0"];
    const stars = Array.from({ length: Math.round(W * H / 4500) }, () => ({
      x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.1 + 0.5,
      a: Math.random() * 0.5 + 0.2, p: Math.random() * 6.28, s: Math.random() * 2 + 0.6,
      c: tints[Math.floor(Math.random() * tints.length)],
    }));
    const draw = (t) => {
      ctx.clearRect(0, 0, W, H);
      for (const s of stars) {
        ctx.globalAlpha = reduced ? s.a : s.a * (0.55 + 0.45 * Math.sin(t / 1000 * s.s + s.p));
        ctx.fillStyle = s.c;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, 6.283);
        ctx.fill();
      }
      if (!reduced && !gone) raf = requestAnimationFrame(draw);
    };
    draw(0);

    const decoded = Promise.all([...el.querySelectorAll("img")].map((i) => i.decode().catch(() => {})));
    Promise.race([decoded, new Promise((r) => setTimeout(r, 1500))]).then(() => {
      if (gone) return;
      clearTimeout(failsafe);
      el.classList.add("ov-play");
      if (!reduced) raf = requestAnimationFrame(draw);
      timer = setTimeout(exit, reduced ? 1200 : 3100);
    });

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
