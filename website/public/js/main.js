document.addEventListener("DOMContentLoaded", () => {
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
