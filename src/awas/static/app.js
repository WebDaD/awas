(() => {
  "use strict";

  const normalize = (value) => value.toLocaleLowerCase("de").trim();

  function initializeMobileMenu() {
    const toggle = document.querySelector("[data-menu-toggle]");
    const menu = document.querySelector("[data-main-menu]");
    if (!toggle || !menu) return;

    const close = () => {
      menu.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-label", "Hauptmenü öffnen");
    };
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      menu.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Hauptmenü schließen" : "Hauptmenü öffnen");
    });
    menu.addEventListener("click", (event) => {
      if (event.target.closest("a")) close();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
    const desktop = window.matchMedia("(min-width: 901px)");
    desktop.addEventListener("change", (event) => {
      if (event.matches) close();
    });
  }

  function applyFilter(input) {
    const name = input.dataset.filterInput;
    const query = normalize(input.value);
    const rows = [...document.querySelectorAll(`[data-filter-row="${name}"]`)];
    let visible = 0;
    for (const row of rows) {
      const searchable = `${row.textContent} ${row.dataset.filterText || ""}`;
      const matches = !query || normalize(searchable).includes(query);
      row.hidden = !matches;
      const companion = row.nextElementSibling;
      if (
        companion &&
        row.dataset.filterGroup &&
        companion.dataset.filterCompanion === row.dataset.filterGroup
      ) {
        companion.hidden = !matches;
      }
      if (matches) visible += 1;
    }
    const empty = document.querySelector(`[data-filter-empty="${name}"]`);
    if (empty) empty.hidden = visible !== 0;
  }

  function applyFilters() {
    document.querySelectorAll("[data-filter-input]").forEach(applyFilter);
  }

  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-filter-input]")) applyFilter(event.target);
  });

  const actionConfirmationTimers = new WeakMap();

  function resetActionConfirmation(button) {
    const form = button.closest("form");
    const value = form?.querySelector("[data-action-confirm-value]");
    if (value) value.value = "";
    button.classList.remove("is-confirming");
    button.dataset.actionReady = "false";
    button.setAttribute("aria-label", button.dataset.actionInitialLabel || "Aktion");
    const timer = actionConfirmationTimers.get(button);
    if (timer) window.clearTimeout(timer);
    actionConfirmationTimers.delete(button);
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action-confirm]");
    if (!button) return;
    if (button.dataset.actionReady === "true") {
      const timer = actionConfirmationTimers.get(button);
      if (timer) window.clearTimeout(timer);
      return;
    }

    event.preventDefault();
    const form = button.closest("form");
    const value = form?.querySelector("[data-action-confirm-value]");
    if (!form || !value) return;
    value.value = "true";
    button.dataset.actionReady = "true";
    button.dataset.actionInitialLabel ||=
      button.querySelector(".action-initial-label")?.textContent.trim() || "Aktion";
    button.classList.add("is-confirming");
    const prompt =
      button.querySelector(".action-confirm-label")?.textContent.trim() || "Wirklich ausführen?";
    button.setAttribute(
      "aria-label",
      `${prompt} Zum Bestätigen binnen fünf Sekunden erneut anklicken.`
    );
    actionConfirmationTimers.set(
      button,
      window.setTimeout(() => resetActionConfirmation(button), 5000)
    );
  });

  function initializeStreamDefaults() {
    document.querySelectorAll("form").forEach((form) => {
      const stream = form.querySelector("[data-stream-select]");
      const recorder = form.querySelector("[data-recorder-select]");
      const fileType = form.querySelector("[data-file-type-select]");
      if (!stream || stream.dataset.defaultsBound === "true") return;
      const selectPreferred = () => {
        const option = stream.options[stream.selectedIndex];
        const preferred = option?.dataset.preferredRecorder;
        if (preferred && recorder) recorder.value = preferred;
        const preferredFileType = option?.dataset.preferredFileType;
        if (preferredFileType && fileType) fileType.value = preferredFileType;
      };
      if (
        (!recorder || !recorder.dataset.initialValue) &&
        (!fileType || !fileType.dataset.initialValue)
      ) {
        selectPreferred();
      }
      stream.addEventListener("change", selectPreferred);
      stream.dataset.defaultsBound = "true";
    });
  }

  function fileNameBase(value) {
    return value
      .toLocaleLowerCase("de")
      .replaceAll("ß", "ss")
      .replaceAll("æ", "ae")
      .replaceAll("ø", "o")
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^[-_]+|[-_]+$/g, "")
      .slice(0, 128);
  }

  function initializeFileNames() {
    document.querySelectorAll("form").forEach((form) => {
      const title = form.querySelector("[data-file-title]");
      const fileName = form.querySelector("[data-file-name-base]");
      if (!title || !fileName || fileName.dataset.bound === "true") return;
      let automatic = !fileName.dataset.initialValue;
      const update = () => {
        if (automatic) fileName.value = fileNameBase(title.value);
      };
      title.addEventListener("input", update);
      fileName.addEventListener("input", () => {
        automatic = false;
      });
      fileName.dataset.bound = "true";
      update();
    });
  }

  function initializeRecurrenceFields() {
    document.querySelectorAll("[data-recurrence-type]").forEach((select) => {
      if (select.dataset.bound === "true") return;
      const form = select.closest("form");
      if (!form) return;
      const update = () => {
        const unit = form.querySelector("[data-recurrence-unit]");
        const units = {
          hourly: "Stunden",
          daily: "Tage",
          weekly: "Wochen",
          monthly_day: "Monate",
          monthly_weekday: "Monate",
        };
        if (unit) unit.textContent = units[select.value] || "Einheiten";
        form.querySelectorAll("[data-recurrence-fields]").forEach((group) => {
          const active = group.dataset.recurrenceFields === select.value;
          group.hidden = !active;
          group.querySelectorAll("input, select").forEach((control) => {
            control.disabled = !active;
            if (control.matches("[data-pattern-required]")) control.required = active;
          });
        });
      };
      select.addEventListener("change", update);
      select.dataset.bound = "true";
      update();
    });
  }

  async function refreshLiveRegions() {
    if (document.hidden) return;
    if (document.querySelector("[data-action-confirm].is-confirming")) return;
    const regions = [...document.querySelectorAll("[data-live-region]")];
    if (!regions.length) return;
    const response = await fetch(window.location.href, {
      credentials: "same-origin",
      headers: { "X-AWAS-Live": "1" },
    });
    if (!response.ok || response.redirected) return;
    const html = await response.text();
    const nextDocument = new DOMParser().parseFromString(html, "text/html");
    for (const region of regions) {
      const name = region.dataset.liveRegion;
      const replacement = nextDocument.querySelector(`[data-live-region="${name}"]`);
      if (replacement) region.innerHTML = replacement.innerHTML;
    }
    applyFilters();
  }

  function startLiveUpdates() {
    const page = document.querySelector("[data-live-page]");
    if (!page) return;
    const interval = Number.parseInt(page.dataset.liveInterval || "5000", 10);
    let refreshing = false;
    window.setInterval(async () => {
      if (refreshing) return;
      refreshing = true;
      try {
        await refreshLiveRegions();
      } catch (_error) {
        // The next interval retries without interrupting the current page.
      } finally {
        refreshing = false;
      }
    }, Math.max(1000, interval));
  }

  initializeMobileMenu();
  applyFilters();
  initializeStreamDefaults();
  initializeFileNames();
  initializeRecurrenceFields();
  startLiveUpdates();
})();
