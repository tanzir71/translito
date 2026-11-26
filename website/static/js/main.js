document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("locale-toggle");
    const fallback = document.getElementById("locale-fallback");
    const menu = document.getElementById("locale-menu");
    if (toggle && fallback && menu) {
        fallback.replaceWith(menu);
        menu.hidden = true;
        toggle.hidden = false;
        const close = () => { menu.hidden = true; toggle.setAttribute("aria-expanded", "false"); };
        toggle.addEventListener("click", () => {
            menu.hidden = !menu.hidden;
            toggle.setAttribute("aria-expanded", String(!menu.hidden));
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && !menu.hidden) { close(); toggle.focus(); }
        });
        document.addEventListener("click", (event) => {
            if (!menu.contains(event.target) && !toggle.contains(event.target)) close();
        });
    }
    const links = [...document.querySelectorAll("[data-locale-choice]")];
    const storageKey = "translito.site.locale";
    links.forEach((link) => link.addEventListener("click", () => {
        try { localStorage.setItem(storageKey, link.dataset.localeChoice); } catch (_) { /* Storage can be disabled. */ }
    }));
    const root = document.documentElement;
    if (root.dataset.siteLocale === "en" && root.dataset.home === "true") {
        try {
            const remembered = localStorage.getItem(storageKey);
            const destination = links.find((link) => link.dataset.localeChoice === remembered);
            if (remembered !== "en" && destination) window.location.replace(destination.href);
        } catch (_) { /* Plain language links remain available. */ }
    }
    document.querySelectorAll('a[href^="#"]').forEach((link) => {
        link.addEventListener("click", (event) => {
            const target = document.querySelector(link.getAttribute("href"));
            if (!target) return;

            event.preventDefault();
            const offset = target.getBoundingClientRect().top + window.scrollY - 72;
            window.scrollTo({ top: offset, behavior: "smooth" });
        });
    });
});
