function heroGeometry(width, layout = "home") {
    if (layout === "language") {
        const ratio = width / 560;
        return { scale: ratio * 918.974 / 1120, left: -179 * ratio, top: -188 * ratio };
    }
    if (width <= 727) {
        const ratio = width / 350;
        return { scale: ratio * 396.46 / 1120, left: -46 * ratio, top: -102 * ratio };
    }
    return { scale: width / 1120, left: 0, top: 0 };
}

document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".hero-shot").forEach((shot) => {
        const scene = shot.querySelector(".shot-scene");
        const resize = () => {
            const geometry = heroGeometry(shot.getBoundingClientRect().width, shot.dataset.layout);
            scene.style.transform = `scale(${geometry.scale})`;
            scene.style.left = `${geometry.left}px`;
            scene.style.top = `${geometry.top}px`;
        };
        resize();
        if (typeof ResizeObserver !== "undefined") new ResizeObserver(resize).observe(shot);
        else window.addEventListener("resize", resize);
        const bar = shot.querySelector(".subtitle-bar");
        shot.querySelector("[data-demo-pause]")?.addEventListener("click", (event) => {
            const paused = bar.classList.toggle("is-paused");
            event.currentTarget.setAttribute("aria-pressed", String(paused));
        });
        let zoom = 1;
        shot.querySelectorAll("[data-demo-size]").forEach((button) => button.addEventListener("click", () => {
            zoom = Math.max(.75, Math.min(1.25, zoom + Number(button.dataset.demoSize) * .1));
            bar.style.setProperty("--subtitle-zoom", String(zoom));
        }));
        shot.querySelector("[data-demo-close]")?.addEventListener("click", () => { bar.hidden = true; });
        shot.querySelector("[data-demo-dismiss]")?.addEventListener("click", () => { shot.querySelector(".start-notice").hidden = true; });
    });
    const mobileMenu = document.querySelector(".mobile-menu");
    const header = document.querySelector(".site-header");
    if (mobileMenu && header) {
        mobileMenu.addEventListener("click", () => {
            const open = header.classList.toggle("nav-open");
            mobileMenu.setAttribute("aria-expanded", String(open));
        });
        document.querySelectorAll(".nav-links a").forEach((link) => link.addEventListener("click", () => {
            header.classList.remove("nav-open"); mobileMenu.setAttribute("aria-expanded", "false");
        }));
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && header.classList.contains("nav-open")) {
                header.classList.remove("nav-open"); mobileMenu.setAttribute("aria-expanded", "false"); mobileMenu.focus();
            }
        });
    }
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
            window.scrollTo({ top: offset, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
        });
    });
});
