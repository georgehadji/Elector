// Inlined in <head> of every page, before the CSS applies: a saved choice is set before first paint (no flash).
// Without a saved choice the page follows the system setting.
(() => {
  const root = document.documentElement, sys = matchMedia("(prefers-color-scheme: dark)");
  // State "system" | "light" | "dark". A press flips the appearance; flipping to the system's own appearance
  // means "follow the system again", so the choice never gets stuck.
  const next = (state, sysDark) => {
    const dark = state === "system" ? sysDark : state === "dark";
    const want = dark ? "light" : "dark";
    return (want === "dark") === sysDark ? "system" : want;
  };
  let state = "system";
  try { const t = localStorage.getItem("theme"); if (t === "light" || t === "dark") state = t; } catch {}
  const show = () => state === "system" ? root.removeAttribute("data-theme") : root.dataset.theme = state;
  show();
  const dark = () => state === "system" ? sys.matches : state === "dark";
  addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("theme");
    if (!b) return;
    const sync = () => b.setAttribute("aria-pressed", dark());
    sync();
    sys.addEventListener("change", sync);
    b.onclick = () => {
      state = next(state, sys.matches);
      show();
      try { state === "system" ? localStorage.removeItem("theme") : localStorage.setItem("theme", state); } catch {}
      sync();
      dispatchEvent(new Event("themechange"));  // map pages redraw: their colours are read from CSS variables
    };
  });
})();
