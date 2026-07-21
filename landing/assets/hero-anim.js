// Hero "flagged -> fixed" typewriter animation.
//
// The hero code card rests on the fixed workflow. On hover (or the replay
// button) it briefly shows the flagged "before" workflow, then types the fixed
// "after" workflow line by line, like the AI rewriting it live. Honours
// prefers-reduced-motion by staying on the static fixed state.
(function () {
  "use strict";

  var card = document.querySelector(".hero__code-card");
  if (!card) return;
  var anim = card.querySelector(".wf-anim");
  if (!anim) return;

  var afterLines = Array.prototype.slice.call(
    anim.querySelectorAll(".wf-anim__after .tw-ln")
  );
  var replay = card.querySelector(".hero__replay");
  var reduce =
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var PER_CHAR = 13; // ms per character
  var BEFORE_HOLD = 1100; // ms the flagged workflow is shown
  var timers = [];
  var playing = false;

  function clearTimers() {
    timers.forEach(clearTimeout);
    timers = [];
  }

  function later(fn, ms) {
    timers.push(setTimeout(fn, ms));
  }

  function reset() {
    clearTimers();
    anim.classList.remove("is-showing-before", "is-typing");
    afterLines.forEach(function (line) {
      line.style.transition = "";
      line.style.width = "";
      line.classList.remove("is-caret");
    });
    playing = false;
  }

  function typeLine(i, done) {
    if (i >= afterLines.length) {
      done();
      return;
    }
    var line = afterLines[i];
    var chars = line.textContent.replace(/​/g, "").trim().length;
    if (chars === 0) {
      // blank spacer row — reveal instantly, small beat before the next line
      line.style.width = "";
      later(function () {
        typeLine(i + 1, done);
      }, 45);
      return;
    }
    var full = line.scrollWidth;
    var dur = Math.max(120, chars * PER_CHAR);
    line.classList.add("is-caret");
    line.style.width = "0px";
    line.getBoundingClientRect(); // force reflow so the transition runs
    line.style.transition = "width " + dur + "ms steps(" + chars + ", end)";
    line.style.width = full + "px";
    later(function () {
      line.classList.remove("is-caret");
      line.style.transition = "";
      line.style.width = "";
      typeLine(i + 1, done);
    }, dur + 40);
  }

  function play() {
    if (reduce || playing) return;
    reset();
    playing = true;

    // Phase 1: reveal the flagged "before" workflow and clip the fixed lines.
    anim.classList.add("is-typing", "is-showing-before");
    afterLines.forEach(function (line) {
      line.style.width = "0px";
    });

    // Phase 2: hide "before" and type the fixed workflow line by line.
    later(function () {
      anim.classList.remove("is-showing-before");
      typeLine(0, function () {
        anim.classList.remove("is-typing");
        afterLines.forEach(function (line) {
          line.style.width = "";
        });
        playing = false;
      });
    }, BEFORE_HOLD);
  }

  card.addEventListener("mouseenter", play);
  if (replay) {
    replay.addEventListener("click", function (event) {
      event.preventDefault();
      reset();
      play();
    });
  }
})();
