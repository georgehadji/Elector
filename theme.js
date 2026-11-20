// Inlined in <head> of every page, before the CSS applies: a saved choice is set before first paint (no flash).
// Without a saved choice the page follows the system setting.
(() => {
  const root = document.documentElement, sys = matchMedia("(prefers-color-scheme: dark)");
  try { const t = localStorage.getItem("theme"); if (t === "light" || t === "dark") root.dataset.theme = t; } catch {}
  const dark = () => root.dataset.theme ? root.dataset.theme === "dark" : sys.matches;
  addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("theme");
    if (!b) return;
    const sync = () => b.setAttribute("aria-pressed", dark());
    sync();
    sys.addEventListener("change", sync);
    b.onclick = () => {
      root.dataset.theme = dark() ? "light" : "dark";
      try { localStorage.setItem("theme", root.dataset.theme); } catch {}
      sync();
      dispatchEvent(new Event("themechange"));  // map pages redraw: their colours are read from CSS variables
    };
  });
})();
