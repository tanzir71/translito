document.addEventListener("DOMContentLoaded", () => {
    const header = document.querySelector(".header");

    document.querySelectorAll('a[href^="#"]').forEach((link) => {
        link.addEventListener("click", (event) => {
            const target = document.querySelector(link.getAttribute("href"));
            if (!target) return;

            event.preventDefault();
            const offset = target.getBoundingClientRect().top + window.scrollY - 72;
            window.scrollTo({ top: offset, behavior: "smooth" });
        });
    });

    if (header) {
        window.addEventListener("scroll", () => {
            header.style.background = window.scrollY > 24
                ? "rgba(8, 10, 9, 0.94)"
                : "rgba(8, 10, 9, 0.84)";
        }, { passive: true });
    }
});
