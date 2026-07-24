;(() => {
  var STORAGE_KEY = "theme"
  var VALID_THEMES = ["light", "dark", "system"]

  function getStoredTheme() {
    var stored = localStorage.getItem(STORAGE_KEY)
    return VALID_THEMES.indexOf(stored) !== -1 ? stored : "system"
  }

  function resolveTheme(theme) {
    if (theme === "system") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
    }
    return theme
  }

  function applyTheme(theme) {
    var root = document.documentElement
    root.classList.remove("light", "dark")
    root.classList.add(resolveTheme(theme))
  }

  function setTheme(theme) {
    localStorage.setItem(STORAGE_KEY, theme)
    applyTheme(theme)
    updateActiveMenuItem(theme)
  }

  function updateActiveMenuItem(theme) {
    var items = document.querySelectorAll(".theme-menu__item")
    items.forEach((item) => {
      item.setAttribute(
        "data-active",
        item.getAttribute("data-theme") === theme ? "true" : "false",
      )
    })
  }

  function closeMenu(dropdown) {
    dropdown.setAttribute("data-open", "false")
  }

  function wireToggle() {
    var menu = document.querySelector(".theme-menu")
    if (!menu) return

    var button = menu.querySelector(".theme-toggle")
    var dropdown = menu.querySelector(".theme-menu__dropdown")
    if (!button || !dropdown) return

    button.addEventListener("click", (event) => {
      event.stopPropagation()
      var isOpen = dropdown.getAttribute("data-open") === "true"
      dropdown.setAttribute("data-open", isOpen ? "false" : "true")
    })

    dropdown.querySelectorAll(".theme-menu__item").forEach((item) => {
      item.addEventListener("click", () => {
        setTheme(item.getAttribute("data-theme"))
        closeMenu(dropdown)
      })
    })

    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target)) closeMenu(dropdown)
    })

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu(dropdown)
    })

    updateActiveMenuItem(getStoredTheme())
  }

  function watchSystemPreference() {
    var mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
    mediaQuery.addEventListener("change", () => {
      if (getStoredTheme() === "system") applyTheme("system")
    })
  }

  wireToggle()
  watchSystemPreference()
})()
