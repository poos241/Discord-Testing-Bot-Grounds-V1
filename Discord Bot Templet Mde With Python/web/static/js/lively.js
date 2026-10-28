/* ============================================================
   Lively UI helpers — count-ups, entrance animations, change pulses
   ============================================================ */
(function() {

    // Animate a number from 0 to target over ~800ms
    window.countUp = function(el, target, duration) {
        if (!el) return;
        duration = duration || 800;
        var start = 0;
        var startTime = null;
        target = Number(target) || 0;
        function step(ts) {
            if (!startTime) startTime = ts;
            var p = Math.min((ts - startTime) / duration, 1);
            // ease-out
            var eased = 1 - Math.pow(1 - p, 3);
            el.textContent = Math.round(start + (target - start) * eased).toLocaleString();
            if (p < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    };

    // Set text, with a flash animation if the value changed
    window.setTextLive = function(el, value) {
        if (!el) return;
        var str = String(value);
        if (el.textContent !== str) {
            el.textContent = str;
            el.classList.remove("value-changed");
            void el.offsetWidth; // restart animation
            el.classList.add("value-changed");
        }
    };

    // Stagger-fade a list of cards on load
    window.staggerIn = function(selector, maxDelay) {
        var els = document.querySelectorAll(selector);
        maxDelay = maxDelay || 5;
        els.forEach(function(el, i) {
            var cls = "animate-in-" + Math.min(i + 1, maxDelay);
            el.classList.add(cls);
        });
    };

})();

// Scroll-reveal for .reveal sections (base-layout pages).
// Sections already in view show immediately; sections below the fold
// are hidden by JS only until they scroll into view. If this script
// never runs, nothing stays hidden. Honors prefers-reduced-motion.
(function initReveal() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var els = document.querySelectorAll(".reveal");
    if (!els.length) return;
    function show(el) { el.classList.add("is-visible"); el.classList.remove("reveal-pending"); }
    if (!("IntersectionObserver" in window)) { els.forEach(show); return; }
    var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) { show(entry.target); io.unobserve(entry.target); }
        });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    els.forEach(function (el) {
        var r = el.getBoundingClientRect();
        if (r.bottom > 0 && r.top < window.innerHeight) { show(el); }
        else { el.classList.add("reveal-pending"); io.observe(el); }
    });
})();
