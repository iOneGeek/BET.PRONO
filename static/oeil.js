/* Œil du Trader en ligne — éléments communs : logo, pictos des bots, fond de bougies (comme le panneau PC). */
document.body.insertAdjacentHTML("afterbegin", `
<canvas id="bg" aria-hidden="true"></canvas><div class="vignette" aria-hidden="true"></div>
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>
  <linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fbe7a1"/><stop offset=".5" stop-color="#e5b04a"/><stop offset="1" stop-color="#9c6b1a"/></linearGradient>
  <linearGradient id="pgApex" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffe9a6"/><stop offset="1" stop-color="#b9821f"/></linearGradient>
  <linearGradient id="pgSonic" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7dd3fc"/><stop offset="1" stop-color="#2563eb"/></linearGradient>
  <linearGradient id="pgStar" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e9c2ff"/><stop offset="1" stop-color="#c026d3"/></linearGradient>
  <linearGradient id="pgMan" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#bbf7d0"/><stop offset="1" stop-color="#15803d"/></linearGradient>
  <symbol id="pic-apex" viewBox="0 0 24 24"><rect x="1" y="1" width="22" height="22" rx="6.5" fill="url(#pgApex)"/>
    <path d="M4.2 18.2 9.9 8.4l2.9 4.6 2-2.6 5 7.8z" fill="#21170a"/><path d="M9.9 8.4l1.5 2.4-1.5-.5-1.4.7z" fill="#fff4cf"/></symbol>
  <symbol id="pic-sonic" viewBox="0 0 24 24"><rect x="1" y="1" width="22" height="22" rx="6.5" fill="url(#pgSonic)"/>
    <path d="M13.6 3.6 6.4 13.4h4.7l-1.2 7 7.7-10.3h-4.6z" fill="#071631"/></symbol>
  <symbol id="pic-star" viewBox="0 0 24 24"><rect x="1" y="1" width="22" height="22" rx="6.5" fill="url(#pgStar)"/>
    <path d="m12 4.3 2.3 4.7 5.2.8-3.8 3.6.9 5.2L12 16.1l-4.6 2.5.9-5.2-3.8-3.6 5.2-.8z" fill="#22072a"/></symbol>
  <symbol id="pic-man" viewBox="0 0 24 24"><rect x="1" y="1" width="22" height="22" rx="6.5" fill="url(#pgMan)"/>
    <path d="M8 18v-6.5a1.4 1.4 0 0 1 2.8 0V11V6.6a1.4 1.4 0 0 1 2.8 0V11v-.6a1.4 1.4 0 0 1 2.8 0V15a4 4 0 0 1-4 4h-1.6A4 4 0 0 1 8 18z" fill="#062312"/></symbol>
  <symbol id="logo" viewBox="0 0 220 130">
    <path d="M8 66 Q110 -14 212 66 Q110 146 8 66 Z" fill="none" stroke="url(#g)" stroke-width="7" stroke-linejoin="round"/>
    <path d="M34 36 Q110 -12 186 36" fill="none" stroke="url(#g)" stroke-width="3.5" stroke-linecap="round" opacity=".85"/>
    <path d="M34 96 Q110 144 186 96" fill="none" stroke="url(#g)" stroke-width="3.5" stroke-linecap="round" opacity=".85"/>
    <circle cx="110" cy="66" r="40" fill="#0b0b0d" stroke="url(#g)" stroke-width="6"/>
    <rect x="88" y="76" width="9" height="14" rx="1.5" fill="url(#g)"/><rect x="101" y="68" width="9" height="22" rx="1.5" fill="url(#g)"/>
    <rect x="114" y="60" width="9" height="30" rx="1.5" fill="url(#g)"/><rect x="127" y="52" width="9" height="38" rx="1.5" fill="url(#g)"/>
    <polyline points="84,70 100,56 112,62 134,40" fill="none" stroke="url(#g)" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
    <polygon points="140,33 124,37 136,49" fill="url(#g)"/>
  </symbol>
</defs></svg>`);

function drawBg() {
  const c = document.getElementById("bg"), dpr = devicePixelRatio || 1;
  c.width = innerWidth * dpr; c.height = innerHeight * dpr;
  const x = c.getContext("2d"); x.scale(dpr, dpr);
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const draw = (y0, amp, w, alpha) => {
    let p = 0.5; const n = Math.ceil(innerWidth / w) + 2;
    for (let i = 0; i < n; i++) {
      const o = p; p = Math.min(.95, Math.max(.05, p + (rnd() - .48) * .09));
      const hi = Math.max(o, p) + rnd() * .03, lo = Math.min(o, p) - rnd() * .03;
      x.globalAlpha = alpha; x.fillStyle = x.strokeStyle = p >= o ? "#2378d9" : "#d47f3a";
      const cx = i * w + w / 2, Y = v => y0 + (1 - v) * amp;
      x.beginPath(); x.moveTo(cx, Y(hi)); x.lineTo(cx, Y(lo)); x.lineWidth = 1.2; x.stroke();
      x.fillRect(cx - w * .3, Y(Math.max(o, p)), w * .6, Math.max(2, Math.abs(Y(o) - Y(p))));
    }
  };
  x.clearRect(0, 0, innerWidth, innerHeight);
  draw(innerHeight * .05, innerHeight * .45, 14, .55);
  draw(innerHeight * .5, innerHeight * .45, 18, .45);
}
addEventListener("resize", drawBg); drawBg();
