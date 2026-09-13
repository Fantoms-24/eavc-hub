/**
 * Instruction page — TOC scroll spy and mobile drawer.
 */
(function () {
  "use strict";

  var docs = document.getElementById("instr-docs");
  if (!docs) return;

  var toc = document.getElementById("instr-toc");
  var backdrop = document.getElementById("instr-toc-backdrop");
  var toggleBtn = document.getElementById("instr-toc-toggle");
  var closeBtn = document.getElementById("instr-toc-close");
  var links = Array.from(docs.querySelectorAll(".instr-toc__link"));
  var sections = links
    .map(function (a) {
      var id = a.getAttribute("href");
      return id && id.charAt(0) === "#" ? document.querySelector(id) : null;
    })
    .filter(Boolean);

  function setTocOpen(open) {
    document.body.classList.toggle("instr-toc-open", !!open);
    if (backdrop) {
      backdrop.hidden = !open;
      backdrop.setAttribute("aria-hidden", open ? "false" : "true");
    }
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", function () {
      setTocOpen(!document.body.classList.contains("instr-toc-open"));
    });
  }
  if (closeBtn) closeBtn.addEventListener("click", function () { setTocOpen(false); });
  if (backdrop) backdrop.addEventListener("click", function () { setTocOpen(false); });

  links.forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.matchMedia("(max-width: 991.98px)").matches) setTocOpen(false);
    });
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") setTocOpen(false);
  });

  function setActive(id) {
    links.forEach(function (a) {
      var on = a.getAttribute("href") === "#" + id;
      a.classList.toggle("is-active", on);
      if (on) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });
  }

  if ("IntersectionObserver" in window && sections.length) {
    var obs = new IntersectionObserver(
      function (entries) {
        var visible = entries
          .filter(function (e) { return e.isIntersecting; })
          .sort(function (a, b) { return b.intersectionRatio - a.intersectionRatio; });
        if (visible.length) setActive(visible[0].target.id);
      },
      { root: null, rootMargin: "-20% 0px -55% 0px", threshold: [0, 0.15, 0.4] }
    );
    sections.forEach(function (sec) { obs.observe(sec); });
  } else if (sections.length) {
    setActive(sections[0].id);
  }
})();
