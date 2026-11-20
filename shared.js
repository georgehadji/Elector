// Pure helpers used by more than one page; inlined into pages by web.fill(). No DOM access at load time.
// Search: accents and case folded, Greeklish read as Greek, case endings stripped.
const fold = s => s.normalize("NFD").replace(/\p{M}/gu, "").toUpperCase();
const LATIN = [["TH","Θ"],["CH","Χ"],["PS","Ψ"],["KS","Ξ"],["OU","ΟΥ"],["A","Α"],["B","Β"],["V","Β"],["G","Γ"],["D","Δ"],["E","Ε"],
  ["Z","Ζ"],["H","Η"],["I","Ι"],["K","Κ"],["C","Κ"],["L","Λ"],["M","Μ"],["N","Ν"],["X","Ξ"],["O","Ο"],["P","Π"],["R","Ρ"],
  ["S","Σ"],["T","Τ"],["Y","Υ"],["F","Φ"],["W","Ω"],["U","ΟΥ"]];
const greek = s => LATIN.reduce((t, [a, b]) => t.replaceAll(a, b), s);  // Greeklish: "patra" finds Πάτρα
// Case endings off (ministry names are genitive: Πατρέων, Ρόδου), then vowels that sound alike merged.
const stem = w => { const m = w.match(/^(.{2,}?)(ΕΩΝ|ΙΩΝ|ΕΩΣ|ΟΥΣ|ΟΥ|ΩΝ|ΟΣ|ΗΣ|ΑΣ|ΕΣ|ΩΣ|ΑΙ|ΟΙ|ΕΙ|Α|Η|Ο|Ι|Ε|Σ|Υ|Ω)$/); return m ? m[1] : w; };
const phon = w => w.replace(/ΕΙ|ΟΙ|Η|Υ/g, "Ι").replace(/ΑΙ/g, "Ε").replace(/Ω/g, "Ο");
const key = w => phon(stem(w));
// A query word hits a place word that starts with it as typed, or shares its stem. Short stems must match
// whole, so "Ρόδος" (ΡΟΔ) finds Ρόδου but not Ροδόπης. `ws` = [[word, key(word)], ...].
const hitsK = (ws, q, k) => ws.some(([w, wk]) => w.startsWith(q) || wk === k || (k.length >= 4 && wk.startsWith(k)));  // k = key(q), computed once per query
const hits = (ws, q) => hitsK(ws, q, key(q));
const queryWords = s => greek(fold(s.trim())).split(/[^\p{L}\d]+/u).filter(Boolean);

// Legend wording, one for every page: lo = -Infinity is the open lower end, hi = undefined the open upper end.
const binLabel = (lo, hi, f) => lo === -Infinity ? `κάτω από ${f(hi)}` : hi === undefined ? `${f(lo)} και πάνω` : `${f(lo)} έως ${f(hi)}`;

// Motion: reduced-motion users get jumps instead of animated zooms.
const MOTION = !matchMedia("(prefers-reduced-motion: reduce)").matches;
const mapOptions = extra => ({zoomAnimation: MOTION, fadeAnimation: MOTION, markerZoomAnimation: MOTION, zoomSnap: 0.25, ...extra});

// Footer "Αντιγραφή συνδέσμου": copies the current address (with the hash) and says so for 2 seconds.
// Without the clipboard API the address goes into a selected read-only field to copy by hand.
document.addEventListener("click", async e => {
  const b = e.target.closest(".copy");
  if (!b) return;
  const done = () => { const t = b.textContent; b.textContent = "Αντιγράφηκε"; setTimeout(() => { b.textContent = t; }, 2000); };
  try { await navigator.clipboard.writeText(location.href); done(); } catch {
    let f = b.parentNode.querySelector(".copyfield");
    if (!f) { f = Object.assign(document.createElement("input"), {readOnly: true, className: "copyfield"}); b.parentNode.append(f); }
    f.value = location.href; f.select();
  }
});
