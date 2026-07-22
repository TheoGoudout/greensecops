// Hero "flagged -> fixed" workflow animation.
//
// The hero code card tells the GreenSecOps story in four phases, driven when
// the card first scrolls into view (and re-run by the replay button):
//
//   1. analyzing — the unfixed workflow is shown plainly while the result card
//      reads grade "?" (scanning).
//   2. flagging  — each non-compliant line is highlighted one by one; the grade
//      drops to "D" and the issue count appears.
//   3. fixing    — the fixed workflow is typed in: unchanged scaffolding snaps
//      in, new/rewritten lines type out, and the issue count ticks down to 0.
//   4. fixed     — the card rests on the compliant workflow at grade "A+++".
//
// Honours prefers-reduced-motion by staying on the static fixed state (the
// card's resting markup already shows the fixed workflow and A+++).
(function () {
  "use strict";

  var card = document.querySelector(".hero__code-card");
  if (!card) return;
  var anim = card.querySelector(".wf-anim");
  if (!anim) return;

  var afterLines = Array.prototype.slice.call(
    anim.querySelectorAll(".wf-anim__after .tw-ln")
  );
  var flagLines = Array.prototype.slice.call(
    anim.querySelectorAll(".wf-anim__before .tw-ln--flag")
  );
  var replay = card.querySelector(".hero__replay");

  // Result card next to the code card — grade badge, title, sub-line, check.
  var visual = card.closest(".hero__visual") || document;
  var gradeEl = visual.querySelector(".hero__result-grade");
  var titleEl = visual.querySelector(".hero__result-title");
  var subEl = visual.querySelector(".hero__result-sub");
  var checkEl = visual.querySelector(".hero__result-check");

  var reduce =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var PER_CHAR = 8; // ms per typed character
  var MAX_LINE = 260; // cap so a single long line never dominates the sequence
  var ANALYZE_HOLD = 750; // ms the unfixed workflow is shown before flagging
  var FLAG_STAGGER = 260; // ms between each error highlight
  var FLAG_HOLD = 550; // ms the fully-flagged workflow is held before fixing
  var SAME_BEAT = 22; // ms pause when an unchanged line snaps in

  var ISSUE_TOTAL = 3; // distinct issues advertised (1 critical, 2 high)

  // All grade modifier classes, so setGrade can swap cleanly between them.
  var GRADE_CLASSES = ["grade-badge--unknown", "grade-badge--d", "grade-badge--aaa"];

  var timers = [];
  var playing = false;

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function later(fn, ms) {
    timers.push(setTimeout(fn, ms));
  }

  function setGrade(modifier, text) {
    if (!gradeEl) return;
    GRADE_CLASSES.forEach(function (c) {
      gradeEl.classList.remove(c);
    });
    gradeEl.classList.add(modifier);
    gradeEl.textContent = text;
  }

  function setResult(title, sub, showCheck) {
    if (titleEl) titleEl.textContent = title;
    if (subEl) subEl.textContent = sub;
    if (checkEl) checkEl.style.display = showCheck ? "" : "none";
  }

  function fixingSub(remaining) {
    if (remaining <= 0) return "Applying AI fix · all issues resolved";
    return (
      "Applying AI fix · " +
      remaining +
      (remaining === 1 ? " issue remaining" : " issues remaining")
    );
  }

  // Reset all animated state back to the flagged/unfixed view.
  function reset() {
    clearTimers();
    anim.classList.remove("is-typing", "is-showing-before");
    afterLines.forEach(function (line) {
      line.style.transition = "";
      line.style.width = "";
      line.classList.remove("is-caret");
    });
    flagLines.forEach(function (line) {
      line.classList.remove("is-flag-on");
    });
    playing = false;
  }

  // Result card at its resting "fixed" values (A+++, no issues, check shown).
  function showFixedResult() {
    setGrade("grade-badge--aaa", "A+++");
    setResult(
      "Analysis complete — deploy.yml",
      "5 categories · 0 critical issues · AI fix available",
      true
    );
  }

  // Rest on the compliant workflow (also the reduced-motion / no-JS-fallback state).
  function showFixed() {
    reset();
    showFixedResult();
  }

  // --- Phase 3: type the fixed workflow in line by line ---
  function typeLine(i, remaining, seen, done) {
    if (i >= afterLines.length) {
      done();
      return;
    }
    var line = afterLines[i];

    // Unchanged scaffolding: reveal instantly, small beat before the next line.
    if (line.getAttribute("data-op") === "same") {
      line.style.transition = "";
      line.style.width = "";
      line.classList.remove("is-caret");
      later(function () {
        typeLine(i + 1, remaining, seen, done);
      }, SAME_BEAT);
      return;
    }

    var chars = line.textContent.replace(/​/g, "").trim().length;
    if (chars === 0) {
      line.style.width = "";
      later(function () {
        typeLine(i + 1, remaining, seen, done);
      }, 45);
      return;
    }

    var full = line.scrollWidth;
    var dur = Math.min(MAX_LINE, Math.max(110, chars * PER_CHAR));
    line.classList.add("is-caret");
    line.style.width = "0px";
    line.getBoundingClientRect(); // force reflow so the transition runs
    line.style.transition = "width " + dur + "ms steps(" + chars + ", end)";
    line.style.width = full + "px";
    later(function () {
      line.classList.remove("is-caret");
      line.style.transition = "";
      line.style.width = "";

      // Each new fix resolves an issue — tick the count down once per category.
      var category = line.getAttribute("data-fix");
      if (category && !seen[category]) {
        seen[category] = true;
        remaining -= 1;
        setResult("Applying AI fix — deploy.yml", fixingSub(remaining), false);
      }
      typeLine(i + 1, remaining, seen, done);
    }, dur + 40);
  }

  function enterFixing() {
    setGrade("grade-badge--d", "D");
    setResult("Applying AI fix — deploy.yml", fixingSub(ISSUE_TOTAL), false);

    // Fade the flagged overlay out; the fixed lines type in underneath it.
    anim.classList.remove("is-showing-before");
    typeLine(0, ISSUE_TOTAL, {}, function () {
      anim.classList.remove("is-typing");
      afterLines.forEach(function (line) {
        line.style.width = "";
      });
      flagLines.forEach(function (line) {
        line.classList.remove("is-flag-on");
      });
      showFixedResult();
      playing = false;
    });
  }

  // --- Phase 2: highlight the flagged lines one by one ---
  function enterFlagging() {
    setGrade("grade-badge--d", "D");
    setResult("Issues found — deploy.yml", "1 critical · 2 high-severity issues", false);

    flagLines.forEach(function (line, idx) {
      later(function () {
        line.classList.add("is-flag-on");
      }, idx * FLAG_STAGGER);
    });

    later(enterFixing, flagLines.length * FLAG_STAGGER + FLAG_HOLD);
  }

  // --- Phase 1: show the unfixed workflow while "analyzing" ---
  function play() {
    if (reduce || playing) return;
    reset();
    playing = true;

    // Reveal the flagged "before" layer and clip the fixed lines to width 0.
    anim.classList.add("is-typing", "is-showing-before");
    afterLines.forEach(function (line) {
      line.style.width = "0px";
    });

    setGrade("grade-badge--unknown", "?");
    setResult("Analyzing deploy.yml…", "Scanning…", false);

    later(enterFlagging, ANALYZE_HOLD);
  }

  if (reduce) {
    showFixed();
    return;
  }

  // Kick off once the card scrolls into view.
  if ("IntersectionObserver" in window) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            observer.disconnect();
            play();
          }
        });
      },
      { threshold: 0.5 }
    );
    observer.observe(card);
  } else {
    play();
  }

  if (replay) {
    replay.addEventListener("click", function (event) {
      event.preventDefault();
      clearTimers();
      playing = false;
      play();
    });
  }
})();
