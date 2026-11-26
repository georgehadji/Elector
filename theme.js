// Inlined in <head> of every page, before the CSS applies: a saved choice is set before first paint (no flash).
// The default is light whatever the system says; the toggle flips light and dark, and only "dark" is remembered.
(() => {
  const root = document.documentElement;
  let dark = false;
  try { dark = localStorage.getItem("theme") === "dark"; } catch {}
  const show = () => {
    dark ? root.dataset.theme = "dark" : root.removeAttribute("data-theme");
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#15171b" : "#fbfaf6");  // the browser bar follows the page
  };
  show();
  addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("theme");
    if (!b) return;
    const sync = () => b.setAttribute("aria-pressed", dark);
    sync();
    b.onclick = () => {
      dark = !dark;
      const go = () => { show(); sync(); dispatchEvent(new Event("themechange")); };
      if (document.startViewTransition && !document.hidden && !matchMedia("(prefers-reduced-motion: reduce)").matches) { const vt = document.startViewTransition(go); vt.ready.catch(() => {}); vt.finished.catch(() => {}); } else go();
      try { dark ? localStorage.setItem("theme", "dark") : localStorage.removeItem("theme"); } catch {}
    };  // themechange: map pages redraw, their colours are read from CSS variables
  });
})();
