/* Œil du Trader — consentement aux cookies (règles de la CNIL), 25/11/2026.

   AUJOURD'HUI : le site n'utilise que des cookies strictement nécessaires (session de connexion, et ce choix-ci).
   La CNIL ne demande pas de consentement pour eux : le bandeau reste donc caché. Le lien « Gérer les cookies »
   du pied de page montre déjà l'état actuel.

   POUR AJOUTER UN JOUR UN TRACEUR OPTIONNEL (mesure d'audience, vidéo intégrée, etc.) :
   1. l'ajouter dans TRACEURS_OPTIONNELS ci-dessous (jamais en <script src=…> dans les pages HTML) ;
   2. augmenter VERSION : tout le monde revoit alors le bandeau (un ancien choix ne vaut pas pour un nouveau traceur) ;
   3. décrire le traceur dans la politique de confidentialité (static/confidentialite.html).
   Le bandeau s'affiche alors tout seul, et aucun de ces scripts n'est chargé avant un clic sur « Accepter ». */
(function () {
  "use strict";

  const VERSION = 1;
  const TRACEURS_OPTIONNELS = [
    // Exemple (à ne décommenter qu'avec un vrai outil) :
    // {nom: "Mesure d'audience", fournisseur: "…", finalite: "compter les visites", duree: "13 mois", src: "https://…/script.js"},
  ];

  const COOKIE = "oeil_consentement";
  const DUREE_CHOIX = 182 * 86400;   // la CNIL recommande de garder le choix environ 6 mois, puis de redemander

  function lireChoix() {
    const m = document.cookie.match(/(?:^|;\s*)oeil_consentement=([^;]*)/);
    if (!m) return null;
    const [v, choix] = decodeURIComponent(m[1]).split(":");
    return +v === VERSION && (choix === "accepte" || choix === "refuse") ? choix : null;   // nouvelle version = nouveau choix
  }

  function ecrireChoix(choix) {
    const sur = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${COOKIE}=${encodeURIComponent(VERSION + ":" + choix)}; Max-Age=${DUREE_CHOIX}; Path=/; SameSite=Lax${sur}`;
  }

  let charges = false;
  function chargerTraceurs() {   // SEULEMENT après « Accepter »
    if (charges) return;
    charges = true;
    for (const t of TRACEURS_OPTIONNELS) {
      if (!t.src) continue;
      const s = document.createElement("script");
      s.src = t.src; s.async = true;
      document.head.appendChild(s);
    }
  }

  function esc(x) { return String(x).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }

  // ---------------------------------------------------------------- bandeau (seulement s'il y a des traceurs optionnels)
  function boutons() {
    // même taille, même style, même place : refuser est aussi simple qu'accepter
    return `<div class="ck-btns"><button type="button" class="ck-btn" data-ck="refuse">Refuser</button>` +
           `<button type="button" class="ck-btn" data-ck="accepte">Accepter</button></div>`;
  }

  function fermerBandeau() { const b = document.getElementById("ckBandeau"); if (b) b.remove(); }

  function montrerBandeau() {
    if (document.getElementById("ckBandeau")) return;
    const b = document.createElement("div");
    b.id = "ckBandeau"; b.className = "ck-bandeau"; b.setAttribute("role", "region"); b.setAttribute("aria-label", "Cookies");
    b.innerHTML = `<p><b>Cookies.</b> Avec ton accord, ce site utilise aussi : ${TRACEURS_OPTIONNELS.map(t => esc(t.nom)).join(", ")}.
      Tu peux refuser sans aucune gêne : le site marche pareil. <a href="/confidentialite">En savoir plus</a></p>${boutons()}`;
    document.body.appendChild(b);
  }

  // ---------------------------------------------------------------- fenêtre « Gérer les cookies »
  function ouvrirGestion() {
    fermerGestion();
    const choix = lireChoix(), n = TRACEURS_OPTIONNELS.length;
    const etat = !n ? "Aucun traceur optionnel n'est utilisé : il n'y a rien à accepter ni à refuser."
      : choix === "accepte" ? "Ton choix actuel : <b>accepté</b>." : choix === "refuse" ? "Ton choix actuel : <b>refusé</b>." : "Tu n'as pas encore fait de choix.";
    const opt = n ? `<ul>${TRACEURS_OPTIONNELS.map(t => `<li><b>${esc(t.nom)}</b>${t.fournisseur ? ` (${esc(t.fournisseur)})` : ""} : ${esc(t.finalite || "")}${t.duree ? `, conservé ${esc(t.duree)}` : ""}</li>`).join("")}</ul>` : "";
    const f = document.createElement("div");
    f.id = "ckGestion"; f.className = "ck-voile";
    f.innerHTML = `<div class="ck-fenetre" role="dialog" aria-modal="true" aria-labelledby="ckTitre">
      <h2 id="ckTitre">Gérer les cookies</h2>
      <p><b>Toujours actifs, car indispensables</b> (pas besoin d'accord) :</p>
      <ul><li><b>Session</b> : garde ta connexion ouverte (30 jours au plus).</li>
          <li><b>Ton choix sur les cookies</b> : retient ta réponse (6 mois), seulement si tu en as donné une.</li></ul>
      <p><b>Optionnels :</b> ${n ? "" : "aucun."}</p>${opt}
      <p class="ck-etat">${etat}</p>
      ${n ? boutons() : ""}
      <div class="ck-bas"><a href="/confidentialite">Politique de confidentialité</a><button type="button" class="ck-lien" data-ck="fermer">Fermer</button></div>
    </div>`;
    document.body.appendChild(f);
    const premier = f.querySelector("button"); if (premier) premier.focus();
  }

  function fermerGestion() { const f = document.getElementById("ckGestion"); if (f) f.remove(); }

  function choisir(choix) {
    const avant = lireChoix();
    ecrireChoix(choix);
    fermerBandeau(); fermerGestion();
    if (choix === "accepte") chargerTraceurs();
    else if (avant === "accepte") location.reload();   // retrait de l'accord : on recharge sans les scripts optionnels
  }

  document.addEventListener("click", e => {
    const ouvrir = e.target.closest && e.target.closest("[data-cookies]");
    if (ouvrir) { e.preventDefault(); ouvrirGestion(); return; }
    const b = e.target.closest && e.target.closest("[data-ck]");
    if (!b) return;
    if (b.dataset.ck === "fermer") fermerGestion(); else choisir(b.dataset.ck);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") fermerGestion(); });

  function demarrer() {
    if (!TRACEURS_OPTIONNELS.length) return;   // aujourd'hui : rien à demander, aucun bandeau
    const choix = lireChoix();
    if (choix === "accepte") chargerTraceurs();
    else if (!choix) montrerBandeau();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer); else demarrer();

  window.oeilCookies = {ouvrir: ouvrirGestion, choix: lireChoix};
})();
