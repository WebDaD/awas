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

  function filterCompanion(row) {
    const companion = row.nextElementSibling;
    if (
      companion &&
      row.dataset.filterGroup &&
      companion.dataset.filterCompanion === row.dataset.filterGroup
    ) {
      return companion;
    }
    return null;
  }

  function applyFilter(name) {
    const input = document.querySelector(`[data-filter-input="${name}"]`);
    const userSelect = document.querySelector(`[data-filter-user="${name}"]`);
    const query = normalize(input?.value || "");
    const userId = userSelect?.value || "";
    const rows = [...document.querySelectorAll(`[data-filter-row="${name}"]`)];
    let visible = 0;
    for (const row of rows) {
      const companion = filterCompanion(row);
      const searchable = `${row.textContent} ${companion?.textContent || ""} ${
        row.dataset.filterText || ""
      }`;
      const matchesText = !query || normalize(searchable).includes(query);
      const matchesUser = !userId || row.dataset.filterUserId === userId;
      const matches = matchesText && matchesUser;
      row.hidden = !matches;
      if (companion) companion.hidden = !matches;
      if (matches) visible += 1;
    }
    document.querySelectorAll(`[data-filter-empty="${name}"]`).forEach((empty) => {
      empty.hidden = visible !== 0;
    });
  }

  function applyFilters() {
    const names = new Set();
    document.querySelectorAll("[data-filter-input]").forEach((input) => {
      names.add(input.dataset.filterInput);
    });
    document.querySelectorAll("[data-filter-user]").forEach((select) => {
      names.add(select.dataset.filterUser);
    });
    names.forEach(applyFilter);
  }

  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-filter-input]")) {
      applyFilter(event.target.dataset.filterInput);
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-filter-user]")) {
      applyFilter(event.target.dataset.filterUser);
    }
  });

  const serverFilterTimers = new WeakMap();
  const serverFilterRequests = new WeakMap();

  function serverFilterUrl(form) {
    const url = new URL(form.action, window.location.origin);
    for (const [name, value] of new FormData(form)) {
      const normalizedValue = String(value).trim();
      if (normalizedValue) url.searchParams.set(name, normalizedValue);
    }
    return url;
  }

  async function applyServerFilter(form) {
    const activeTimer = serverFilterTimers.get(form);
    if (activeTimer) window.clearTimeout(activeTimer);
    serverFilterTimers.delete(form);

    const previousRequest = serverFilterRequests.get(form);
    if (previousRequest) previousRequest.abort();
    const request = new AbortController();
    serverFilterRequests.set(form, request);
    const url = serverFilterUrl(form);
    form.setAttribute("aria-busy", "true");
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-AWAS-Filter": "1" },
        signal: request.signal,
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      if (!response.ok) throw new Error("filter request failed");
      const html = await response.text();
      const nextDocument = new DOMParser().parseFromString(html, "text/html");
      const region = document.querySelector('[data-live-region="schedule-history"]');
      const replacement = nextDocument.querySelector(
        '[data-live-region="schedule-history"]'
      );
      if (!region || !replacement) throw new Error("filter response incomplete");
      region.replaceWith(replacement);
      window.history.replaceState({}, "", `${url.pathname}${url.search}`);
    } catch (error) {
      if (error.name !== "AbortError") window.location.assign(url);
    } finally {
      if (serverFilterRequests.get(form) === request) {
        serverFilterRequests.delete(form);
        form.removeAttribute("aria-busy");
      }
    }
  }

  function scheduleServerFilter(form) {
    const activeTimer = serverFilterTimers.get(form);
    if (activeTimer) window.clearTimeout(activeTimer);
    serverFilterTimers.set(
      form,
      window.setTimeout(() => applyServerFilter(form), 350)
    );
  }

  document.addEventListener("input", (event) => {
    const input = event.target.closest("[data-server-filter-input]");
    if (!input || event.isComposing) return;
    const form = input.closest("[data-server-filter-form]");
    if (form) scheduleServerFilter(form);
  });

  document.addEventListener("change", (event) => {
    const select = event.target.closest("[data-server-filter-user]");
    if (!select) return;
    const form = select.closest("[data-server-filter-form]");
    if (form) applyServerFilter(form);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-server-filter-form]");
    if (!form) return;
    event.preventDefault();
    applyServerFilter(form);
  });

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        return;
      } catch (_error) {
        // The synchronous fallback also works on local HTTP pages.
      }
    }
    const field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    field.setSelectionRange(0, field.value.length);
    const copied = document.execCommand("copy");
    field.remove();
    if (!copied) throw new Error("copy failed");
  }

  const copyFeedbackTimers = new WeakMap();

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-stream-url]");
    if (!button) return;
    const initialLabel = button.dataset.copyInitialLabel || button.getAttribute("aria-label");
    button.dataset.copyInitialLabel = initialLabel || "Stream-URL kopieren";
    if (
      !button.classList.contains("is-copied") &&
      !button.classList.contains("is-copy-error")
    ) {
      button.dataset.copyInitialScrollLeft = String(button.scrollLeft);
    }
    const previousTimer = copyFeedbackTimers.get(button);
    if (previousTimer) window.clearTimeout(previousTimer);
    try {
      await copyText(button.dataset.copyStreamUrl);
      button.classList.remove("is-copy-error");
      button.classList.add("is-copied");
      button.dataset.copyFeedback = "✓ In Zwischenablage kopiert";
      button.scrollLeft = 0;
      button.setAttribute("aria-label", "Stream-URL kopiert");
      button.title = "Kopiert";
    } catch (_error) {
      button.classList.remove("is-copied");
      button.classList.add("is-copy-error");
      button.dataset.copyFeedback = "Kopieren fehlgeschlagen";
      button.scrollLeft = 0;
      button.setAttribute("aria-label", "Stream-URL konnte nicht kopiert werden");
      button.title = "Kopieren fehlgeschlagen";
    }
    copyFeedbackTimers.set(
      button,
      window.setTimeout(() => {
        button.classList.remove("is-copied", "is-copy-error");
        delete button.dataset.copyFeedback;
        button.scrollLeft = Number(button.dataset.copyInitialScrollLeft || 0);
        button.setAttribute("aria-label", button.dataset.copyInitialLabel);
        button.title = "Stream-URL kopieren";
        copyFeedbackTimers.delete(button);
      }, 2000)
    );
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
    if (document.querySelector('[data-server-filter-form][aria-busy="true"]')) return;
    const regions = [...document.querySelectorAll("[data-live-region]")];
    if (!regions.length) return;
    const requestedUrl = window.location.href;
    const response = await fetch(requestedUrl, {
      credentials: "same-origin",
      headers: { "X-AWAS-Live": "1" },
    });
    if (!response.ok || response.redirected) return;
    const html = await response.text();
    if (requestedUrl !== window.location.href) return;
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
