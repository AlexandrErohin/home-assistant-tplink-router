// Native HA workspace: scan current Wi-Fi first, then inspect and explicitly manage.
// Inherits HA typography, theme and sidebar; no external resources or credentials.
export const escape = value => String(value ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const x = escape;
const connectionLabel = value => ({ host: "Main Wi-Fi", guest: "Guest Wi-Fi", wired: "Wired" }[value] || "Unknown");
const clock = value => `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
export function filterDevices(data, filters) {
  const query = filters.search.trim().toLocaleLowerCase();
  return data.devices.filter(d =>
    (filters.status === "all" || (filters.status === "online" ? d.online && !d.cached : !d.online)) &&
    (filters.connection === "all" || (filters.connection === "wifi" ? ["host", "guest"].includes(d.connection) : d.connection === filters.connection)) &&
    (filters.profile === "all" || data.memberships_available &&
      (filters.profile === "none" ? !d.owners.length : d.owners.includes(filters.profile))) &&
    (!query || [d.name, d.ip, d.mac, ...d.owners.map(id => data.profiles.find(p => p.owner_id === id)?.name)].some(v =>
      String(v || "").toLocaleLowerCase().includes(query)))
  ).sort((a, b) => a.name.localeCompare(b.name) || a.mac.localeCompare(b.mac));
}
export function batchSelectionError(data, macs) {
  if (!macs.length || macs.length > 32 || new Set(macs).size !== macs.length) return "Select 1–32 different devices.";
  if (!data?.memberships_available) return "Current profile memberships are unavailable.";
  if (macs.some(mac => {
    const device = data.devices.find(d => d.mac === mac);
    return !device || device.cached || device.owners.length;
  })) return "A selected device is unavailable or now assigned. Clear the selection and review its individual profile.";
  return "";
}
export class TPLinkNetworkPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.filters = { search: "", status: "online", connection: "wifi", profile: "all" };
    this.tab = "devices";
    this.selected = null;
    this.draft = {};
    this.loading = false;
    this.busy = false;
    this.error = "";
    this.notice = "";
    this.generation = 0;
    this.batchSelection = new Set();
    this.batchDestination = "";
    this.featureGeneration = 0;
    this.creationDraft = {};
    this.onVisibility = () => { if (document.hidden) { this.clearPrivateReport(); this.render(); } };
    this.shadowRoot.addEventListener("input", e => this.input(e));
    this.shadowRoot.addEventListener("change", e => this.input(e));
    this.shadowRoot.addEventListener("click", e => this.click(e));
    this.shadowRoot.addEventListener("submit", e => this.submit(e));
  }
  set hass(value) {
    this._hass = value;
    if (this.isConnected && !this.timer) this.start();
  }
  get hass() { return this._hass; }
  connectedCallback() {
    document.addEventListener("visibilitychange", this.onVisibility);
    if (this.hass && !this.timer) this.start();
  }
  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this.onVisibility);
    clearInterval(this.timer); this.timer = null; this.generation++; this.clearPrivateReport();
  }
  clearPrivateReport() {
    this.report = null; this.featureError = ""; this.featureErrorKind = ""; this.featureLoading = "";
    this.featureGeneration = (this.featureGeneration || 0) + 1;
  }
  async loadFeature(kind, owner_id = "") {
    if (this.unsafe || this.featureLoading) return;
    const generation = this.featureGeneration;
    this.featureLoading = kind; this.featureError = ""; this.report = null; this.render();
    try {
      const data = await this.hass.callWS({
        type: "tplink_router/profile_read", entry_id: this.entryId, kind, ...(owner_id ? { owner_id } : {}),
      });
      if (generation !== this.featureGeneration) return;
      if (kind === "report") {
        if (data.owner_id !== owner_id || !data.insights || !data.history) throw new Error("Report response is incomplete.");
        this.report = data; this.reportLoadedAt = new Date().toLocaleString(); this.reportDay = 0; this.historyLimit = 50;
      } else if (kind === "delete_preview") {
        if (data.owner_id !== owner_id || !Array.isArray(data.members) || !/^[0-9a-f]{64}$/.test(data.revision)) {
          throw new Error("Deletion preview is incomplete; nothing was deleted.");
        }
        this.pending = { action: "delete_profile", owner_id, revision: data.revision };
        this.confirmation = `Permanently delete “${data.name}” and its filters, schedules and budgets? ${data.members.length} assigned devices will lose this profile's protection; other router restrictions may still apply. No automatic retry or undo. If this profile changes before submission, deletion is refused.`;
        this.confirmationDevices = data.members.map(mac =>
          this.data.devices.find(d => d.mac === mac.toLowerCase().replaceAll("-", ":"))?.name || mac);
      } else {
        if (!Array.isArray(data.presets) || !Number.isInteger(data.remaining)) throw new Error("Creation metadata is incomplete.");
        this.creationOptions = data;
      }
    } catch (e) {
      if (generation === this.featureGeneration) {
        this.featureError = e.message || "Profile read failed; retry explicitly."; this.featureErrorKind = kind;
      }
    } finally {
      if (generation === this.featureGeneration) { this.featureLoading = ""; this.render(); }
    }
  }
  start() {
    this.load();
    this.timer = setInterval(() => { if (!this.busy && !this.pending) this.load(true); }, 15000);
  }
  async load(quiet = false) {
    if (this.loading) return;
    const generation = this.generation;
    this.loading = true;
    if (!quiet) this.render();
    try {
      if (!this.routers) this.routers = await this.hass.callWS({ type: "tplink_router/network" });
      if (!this.entryId) this.entryId = this.routers[0]?.entry_id;
      if (this.entryId) {
        const data = await this.hass.callWS({ type: "tplink_router/network", entry_id: this.entryId });
        if (generation !== this.generation) return;
        this.data = data;
      }
      if (!quiet || this.readFailed) this.error = "";
      this.readFailed = false;
    } catch (e) {
      this.error = e.message || "Unable to load network data. Check the router connection and retry.";
      this.readFailed = true;
      if (this.data) this.data = { ...this.data, stale: true, devices: this.data.devices.map(d =>
        ({ ...d, online: false, cached: true })) };
    } finally {
      this.loading = false;
      if (generation === this.generation) this.render();
    }
  }
  input(e) {
    const target = e.target;
    if (target.dataset.batchMac) {
      if (target.checked && !this.batchSelection.has(target.dataset.batchMac) && this.batchSelection.size >= 32) {
        target.checked = false; this.error = "Select at most 32 devices per assignment."; this.render(); return;
      }
      if (target.checked) this.batchSelection.add(target.dataset.batchMac);
      else this.batchSelection.delete(target.dataset.batchMac);
      this.render();
    } else if (target.name === "reportDay") {
      this.reportDay = Number(target.value); this.render();
    } else if (["newName", "newFilter"].includes(target.name)) {
      this.creationDraft[target.name] = target.value;
      if (target.name === "newFilter") this.render();
    } else if (target.name === "batchDestination") {
      this.batchDestination = target.value;
    } else if (target.dataset.filter) {
      this.filters[target.dataset.filter] = target.value;
      this.renderList();
    } else if (target.name) {
      const key = target.form?.id === "profile-access" ? "accessEnabled" : target.name;
      this.draft[key] = target.type === "checkbox" ? target.checked : target.value;
      if (target.name === "enabled") {
        const budget = target.form?.querySelector('input[type="number"]');
        if (budget) budget.required = target.checked;
      }
    }
  }
  async click(e) {
    const button = e.target.closest("button");
    if (!button || button.disabled) return;
    const action = button.dataset.action;
    if (action === "menu") {
      this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
    } else if (action === "tab") {
      this.clearPrivateReport(); this.showCreate = false;
      this.tab = button.dataset.tab; this.selected = null; this.draft = {}; this.render();
      this.shadowRoot.querySelector(`[data-tab="${this.tab}"]`)?.focus();
    } else if (action === "select" || action === "open-device") {
      this.clearPrivateReport(); this.showCreate = false;
      if (action === "open-device") this.tab = "devices";
      this.selected = button.dataset.id; this.draft = {}; this.notice = ""; this.render();
      this.shadowRoot.querySelector("#detail-heading")?.focus();
    } else if (action === "close") {
      this.clearPrivateReport();
      const previous = this.selected;
      this.selected = null; this.draft = {}; this.render();
      [...this.shadowRoot.querySelectorAll("[data-id]")].find(el => el.dataset.id === previous)?.focus();
    } else if (action === "refresh") {
      await this.execute({ action: "refresh" }, "Router refresh requested.");
    } else if (action === "retry") {
      this.readFailed = false; await this.load();
    } else if (action === "select-visible") {
      const visible = filterDevices(this.data, this.filters).filter(d => !d.cached && !d.owners.length);
      const next = new Set([...this.batchSelection, ...visible.map(d => d.mac)]);
      if (next.size > 32) this.error = "More than 32 devices would be selected. Narrow the filters or select individually.";
      else this.batchSelection = next;
      this.render();
    } else if (action === "clear-selection") {
      this.batchSelection.clear(); this.render();
    } else if (action === "new-profile") {
      this.clearPrivateReport(); this.tab = "profiles"; this.selected = null; this.showCreate = true;
      this.creationOptions = null; this.creationDraft = {}; await this.loadFeature("creation_options");
    } else if (action === "creation-options") {
      await this.loadFeature("creation_options");
    } else if (action === "cancel-create") {
      this.clearPrivateReport(); this.showCreate = false; this.creationDraft = {}; this.render();
    } else if (action === "load-report") {
      await this.loadFeature("report", button.dataset.owner);
    } else if (action === "delete-profile") {
      await this.loadFeature("delete_preview", this.selected);
    } else if (action === "clear-report") {
      this.clearPrivateReport(); this.render();
      this.shadowRoot.querySelector("#load-profile-report")?.focus();
    } else if (action === "more-history") {
      this.historyLimit += 50; this.render();
    } else if (action === "confirm") {
      const request = this.pending;
      this.pending = null;
      this.shadowRoot.querySelector("dialog")?.close();
      if (request && (this.unsafe || request.action === "assign_devices" && batchSelectionError(this.data, request.macs))) {
        this.error = "The snapshot is no longer current. Refresh before confirming a change.";
        this.render();
      } else if (request) await this.execute(request, "Change confirmed by router read-back.");
    } else if (action === "cancel") {
      this.pending = null; this.shadowRoot.querySelector("dialog")?.close();
    }
  }
  submit(e) {
    e.preventDefault();
    if (!this.data || this.unsafe) return;
    const form = e.target;
    if (!form.reportValidity()) return;
    const values = Object.fromEntries(new FormData(form));
    let request, description;
    if (form.id === "rename-profile") {
      const profile = this.data.profiles.find(p => p.owner_id === this.selected);
      if (!profile || !profile.assignments_valid) return;
      request = {
        action: "rename_profile", owner_id: profile.owner_id, expected_name: profile.name, name: values.profileName,
      };
      description = `Rename “${profile.name}” to “${values.profileName}”. Profile identity, devices, filters and schedules stay unchanged. Entity IDs are not renamed.`;
    } else if (form.id === "create-profile") {
      const preset = this.creationOptions?.presets.find(p => p.filter_level === values.newFilter);
      if (!preset || this.creationOptions.remaining < 1) return;
      request = {
        action: "create_profile", name: values.newName, filter_level: values.newFilter, categories: preset.categories,
      };
      description = `Create empty profile “${values.newName}” with the ${this.filterLabel(values.newFilter)} preset and ${preset.categories.length} blocked categories shown in the form. No device is assigned or moved. Daily budgets and bedtime rules start disabled. Assign devices separately after creation is confirmed. No automatic retry or deletion.`;
    } else if (form.id === "batch-assign") {
      const macs = [...this.batchSelection];
      const error = batchSelectionError(this.data, macs);
      const destination = this.data.profiles.find(p => p.owner_id === values.batchDestination && p.assignments_valid);
      if (error || !destination) {
        this.error = error || "Choose an existing destination profile."; this.render(); return;
      }
      request = { action: "assign_devices", macs, destination: destination.owner_id };
      description = `Assign ${macs.length} selected unassigned device${macs.length === 1 ? "" : "s"} to ${destination.name}. Its restrictions will apply. Capacity and identities are checked again before one router update. No moves, removals or automatic retries. If the router applies only part, inspect each result before another action.`;
      this.confirmationDevices = macs.map(mac => this.data.devices.find(d => d.mac === mac)?.name || mac);
    } else if (form.id === "profile-change") {
      if (!this.data.memberships_available) {
        this.error = "Profile memberships are unavailable. Refresh before changing an assignment.";
        this.render(); return;
      }
      const device = this.data.devices.find(d => d.mac === this.selected);
      if (!device || device.owners.length > 1) return;
      const source = device.owners[0] || "";
      const destination = values.destination;
      if (source === destination) { this.notice = "This device is already in that profile."; this.render(); return; }
      const label = id => this.data.profiles.find(p => p.owner_id === id)?.name || "Unassigned";
      description = `${device.name}: ${label(source)} → ${label(destination)}. ${
        source && destination ? "A move removes the original assignment first, then applies the destination. Restrictions may be briefly absent. If the second step fails, recovery is attempted and the actual result is shown." :
        destination ? "The destination profile's restrictions will apply." : "This removes the profile's protection from this device."
      } Other devices and schedules will not be edited.`;
      request = { action: "change_profile", mac: device.mac, expected_owner: source, destination };
    } else if (form.id === "profile-access") {
      request = { action: "access", owner_id: this.selected, enabled: values.enabled === "on" };
      description = `${request.enabled ? "Clear manual pause for" : "Manually pause internet access for"} ${
        this.profileName(this.selected)}. Schedules and content filters remain unchanged.`;
    } else if (form.dataset.kind) {
      const kind = form.dataset.kind, period = values.period;
      request = { action: "schedule", owner_id: this.selected, period, kind, enabled: values.enabled === "on" };
      if (kind === "bed_time") Object.assign(request, { begin: values.begin, end: values.end });
      else if (values.minutes !== "") request.minutes = Number(values.minutes);
      description = `Update ${this.profileName(this.selected)} ${period === "workday" ? "workday" : "weekend"} ${
        kind === "bed_time" ? "bedtime window" : "daily online-time budget"
      }: ${kind === "bed_time" ? `${values.begin}–${values.end} (router-local)` :
        values.minutes ? `${values.minutes} minutes/day` : "keep existing unset budget"}. ${
        request.enabled ? "Enable" : "Disable"} this rule. Other rules and device assignments are preserved.`;
    } else return;
    this.pending = request;
    this.confirmation = description;
    this.render();
  }
  async execute(request, success) {
    this.generation++;
    this.clearPrivateReport();
    if (request.action === "assign_devices") this.batchResult = null;
    this.busy = true; this.error = ""; this.notice = ""; this.render();
    try {
      this.data = await this.hass.callWS({ type: "tplink_router/network_action", entry_id: this.entryId, ...request });
      if (request.action === "assign_devices") {
        const result = this.data.assignment_result;
        if (!result || !Array.isArray(result.outcomes) || result.outcomes.length !== request.macs.length ||
          new Set(result.outcomes.map(item => item.mac)).size !== request.macs.length ||
          result.outcomes.some(item => !request.macs.includes(item.mac))) {
          throw new Error("Batch response is incomplete. Inspect every selected device; do not assume assignment succeeded.");
        }
        this.batchResult = result;
        if (result.confirmed && result.outcomes.every(item => item.status === "assigned")) {
          this.notice = `${result.outcomes.length} device assignments confirmed by router read-back.`;
        } else this.error = result.error || "Some assignments are unconfirmed. Inspect the per-device results; no retry was made.";
      } else if (request.action === "create_profile") {
        const result = this.data.creation_result;
        this.showCreate = false; this.creationDraft = {}; this.creationOptions = null;
        if (result?.confirmed && this.data.profiles.some(p => p.owner_id === result.owner_id)) {
          this.tab = "profiles"; this.selected = result.owner_id;
          this.notice = "Empty profile creation confirmed. Assign devices separately; its restrictions apply after assignment.";
        } else this.error = result?.error || "Creation is unconfirmed. Inspect profiles before retrying; no retry was made.";
      } else {
        if (request.action === "delete_profile") {
          this.selected = null; this.confirmationDevices = [];
          this.notice = "Profile deletion confirmed. Other profile settings and memberships were retained.";
        } else this.notice = success;
      }
      this.draft = {}; this.readFailed = false;
    } catch (e) {
      this.error = e.message || "Change could not be confirmed. Refresh and inspect the actual assignment before retrying.";
      if (request.action === "assign_devices") this.batchResult = {
        confirmed: false, outcomes: request.macs.map(mac => ({ mac, status: "unknown" })),
      };
      if (request.action === "create_profile") {
        this.showCreate = false; this.creationDraft = {}; this.creationOptions = null;
        this.error = `${this.error} Inspect profiles before retrying creation.`;
      }
      // Always re-read even on failed writes, without replacing the failure notice.
      try { this.data = await this.hass.callWS({ type: "tplink_router/network", entry_id: this.entryId }); }
      catch { this.readFailed = true; }
    } finally {
      if (request.action === "assign_devices") this.batchSelection.clear();
      this.busy = false; this.render();
    }
  }
  profileName(id) { return this.data?.profiles.find(p => p.owner_id === id)?.name || "Unknown profile"; }
  filterLabel(level) {
    return { toddler: "Toddler", tyke: "Young child", pre_teen: "Pre-teen", teen: "Teen", adult: "Adult" }[level] || level;
  }
  creationForm() {
    if (!this.showCreate) return "";
    const options = this.creationOptions;
    const preset = options?.presets.find(p => p.filter_level === this.creationDraft.newFilter);
    return `<section class="rule" aria-label="Create parental profile"><h2>New parental profile</h2>
      <p>Create an empty profile, then assign devices separately. Existing memberships and settings will not be edited.</p>
      ${this.featureLoading === "creation_options" ? '<p role="status">Loading router capacity and filter presets…</p>' : ""}
      ${this.featureError ? `<p role="alert">${x(this.featureError)}</p>` : ""}
      <button id="creation-options" type="button" data-action="creation-options" ${this.unsafe || this.featureLoading ? "disabled" : ""}>Reload creation options</button>
      ${options ? `<p>${options.remaining} profile slots available (router maximum ${options.maximum}). Capacity and presets are checked again before saving.</p>
      <form id="create-profile"><label>Profile name<input id="newName" name="newName" required maxlength="64" value="${x(this.creationDraft.newName || "")}" autocomplete="off"></label>
      <label>Filter preset<select id="newFilter" name="newFilter" required><option value="">Choose a preset</option>${options.presets.map(p =>
        `<option value="${x(p.filter_level)}" ${p.filter_level === this.creationDraft.newFilter ? "selected" : ""}>${x(this.filterLabel(p.filter_level))}</option>`).join("")}</select></label>
      ${preset ? `<h3>Blocked categories from router preset</h3>${preset.categories.length ? `<ul>${preset.categories.map(c => `<li>${x(c)}</li>`).join("")}</ul>` : "<p>No categories in this preset.</p>"}` : ""}
      <p class="note">No custom websites or applications. Manual pause starts cleared. Both daily budgets start disabled with a stored 120-minute value; both bedtime windows start disabled with stored 22:00–07:00 router-local times.</p>
      <button class="primary" ${this.unsafe || this.featureLoading || !options.remaining ? "disabled" : ""}>Review new profile</button></form>` : ""}
      <button type="button" data-action="cancel-create">Cancel creation</button></section>`;
  }
  reportControls(owner) {
    const report = this.report?.owner_id === owner ? this.report : null;
    const insights = report?.insights, history = report?.history;
    const day = insights?.status === "ok" ? insights.data[this.reportDay || 0] : null;
    return `<section class="profile-report" aria-label="Private profile report"><h3>Profile report</h3>
      <p class="note">${x(this.data.capabilities.reports_reason)} Website labels are router observations, not proof of a person visiting a page. Encrypted traffic and router coverage can make reports incomplete.</p>
      <button id="load-profile-report" type="button" data-action="load-report" data-owner="${x(owner || "")}" ${!owner || this.unsafe || this.featureLoading || !this.data.capabilities.reports ? "disabled" : ""}>${this.featureLoading === "report" ? "Loading private report…" : "Load profile report"}</button>
      ${!owner ? "<p>Choose an assigned profile to view its report.</p>" : `<p class="note">For ${x(this.profileName(owner))}, across all its devices. Loaded only on request; cleared when leaving these details, hiding the page or switching router. Not saved in entity states or Recorder.</p>`}
      ${this.featureError && this.featureErrorKind === "report" ? `<p role="alert">${x(this.featureError)}</p>` : ""}
      ${report ? `<button type="button" data-action="clear-report">Clear private report</button>
      <p class="note">Snapshot loaded ${x(this.reportLoadedAt)}; not refreshed automatically.</p>
      <h4>Daily online time and website labels</h4>
      ${insights.status !== "ok" ? `<p role="alert">${x(insights.error)}</p>` : !insights.data.length ? "<p>No daily records returned by the router.</p>" :
        `<label>Router report period<select id="reportDay" name="reportDay">${insights.data.map((_,i) => `<option value="${i}" ${i === (this.reportDay || 0) ? "selected" : ""}>${i === 0 ? "Today" : i === 1 ? "Yesterday" : `${i} days ago`} (native period ${i})</option>`).join("")}</select></label>
        <p><strong>${x(day.minutes)} minutes online</strong> reported for this profile. Not a byte-usage total.</p>
        ${day.websites.length ? `<table><thead><tr><th>Website label</th><th>Minutes</th><th>Router block flag</th></tr></thead><tbody>${day.websites.map(s =>
          `<tr><td>${x(s.website)}</td><td>${x(s.minutes)}</td><td>${s.blocked ? "Blocked" : "Not flagged"}</td></tr>`).join("")}</tbody></table>` : "<p>No website records for this period.</p>"}`}
      <h4>Recent history returned by router</h4><p class="note">Timestamps shown in this browser's local time zone. Native UI offers seven daily periods; actual history retention/reset coverage is not guaranteed. No per-device attribution.</p>
      ${history.status !== "ok" ? `<p role="alert">${x(history.error)}</p>` : !history.data.length ? "<p>No history records returned by the router.</p>" :
        `<table><thead><tr><th>Observed time</th><th>Website label</th><th>Router block flag</th></tr></thead><tbody>${history.data.slice(0, this.historyLimit || 50).map(s =>
          `<tr><td>${x(new Date(s.timestamp * 1000).toLocaleString())}</td><td>${x(s.website)}</td><td>${s.blocked ? "Blocked" : "Not flagged"}</td></tr>`).join("")}</tbody></table>
        <p>${Math.min(this.historyLimit || 50, history.data.length)} of ${history.data.length} returned records shown.</p>${history.data.length > (this.historyLimit || 50) ? '<button type="button" data-action="more-history">Show 50 more records</button>' : ""}`}` : ""}
      </section>`;
  }
  get unsafe() {
    return this.busy || this.featureLoading || this.readFailed || !this.data?.available || this.data?.stale ||
      this.data?.paused || !this.data?.profiles_available ||
      Date.now() - Date.parse(this.data?.updated_at) > (this.data?.stale_after_seconds ?? 120) * 1000;
  }
  renderList() {
    const list = this.shadowRoot.querySelector("#device-list");
    if (list) list.innerHTML = this.deviceRows();
    const count = this.shadowRoot.querySelector("#result-count");
    if (count && this.data) count.textContent = `${filterDevices(this.data, this.filters).length} devices`;
    const batch = this.shadowRoot.querySelector("#batch-controls");
    if (batch) batch.innerHTML = this.batchControls();
  }
  batchControls() {
    const macs = [...this.batchSelection], visible = filterDevices(this.data, this.filters);
    const hidden = macs.filter(mac => !visible.some(d => d.mac === mac)).length;
    const error = macs.length ? batchSelectionError(this.data, macs) : "";
    return `<div class="selection-summary"><span role="status">${macs.length} selected${hidden ? ` · ${hidden} hidden by filters` : ""}</span>
      <button type="button" data-action="select-visible" ${this.unsafe || !this.data.memberships_available || !visible.some(d => !d.cached && !d.owners.length) ? "disabled" : ""}>Select visible unassigned</button>
      <button type="button" data-action="clear-selection" ${this.busy || !macs.length ? "disabled" : ""}>Clear selection</button></div>
      <p class="note">Select unassigned devices to add together. Assigned devices use individual review for explicit moves. Maximum 32 per request; the router's remaining capacity is checked before any write.</p>
      ${macs.length ? `<form id="batch-assign"><label>Destination for ${macs.length} devices<select name="batchDestination" required ${this.unsafe ? "disabled" : ""}>
      <option value="">Choose an existing profile</option>${this.data.profiles.map(p => `<option value="${x(p.owner_id)}" ${p.owner_id === this.batchDestination ? "selected" : ""} ${p.assignments_valid ? "" : "disabled"}>${x(p.name)}</option>`).join("")}</select></label>
      ${error ? `<p role="status">${x(error)}</p>` : ""}
      <button class="primary" ${this.unsafe || error ? "disabled" : ""}>Review ${macs.length} assignments</button></form>` : ""}`;
  }
  batchResults() {
    if (!this.batchResult) return "";
    const labels = {
      assigned: "Assignment confirmed", assigned_unconfirmed: "Assigned, but protected settings or acknowledgement not confirmed — do not retry",
      not_assigned: "Not assigned in read-back", conflict: "Conflicting identity or ownership — inspect before another action",
      unknown: "Outcome unknown — inspect before another action",
    };
    return `<section class="batch-results" aria-label="Assignment results"><h2>Last assignment results</h2><ul>${this.batchResult.outcomes.map(item =>
      `<li><strong>${x(this.data?.devices.find(d => d.mac === item.mac)?.name || item.mac)}</strong>: ${x(labels[item.status] || labels.unknown)}</li>`
    ).join("")}</ul><p class="note">Captured at action read-back; see the device list for current membership. No automatic retry or rollback was performed.</p></section>`;
  }
  deviceRows() {
    if (!this.data) return "";
    const devices = filterDevices(this.data, this.filters);
    if (!devices.length) return `<div class="empty"><h3>No matching devices</h3><p>Try All states, another connection, or clear your search. Offline and cached devices are never counted as online.</p></div>`;
    return devices.map(d => `<div class="device-item"><label class="device-check" title="${d.owners.length ? "Already assigned; use individual review to move" : d.cached ? "Cached device; refresh before selecting" : "Select for assignment"}"><input
      id="batch-${x(d.mac.replaceAll(":", ""))}" data-batch-mac="${x(d.mac)}" type="checkbox" aria-label="Select ${x(d.name)} for assignment" ${this.batchSelection?.has(d.mac) ? "checked" : ""}
      ${this.busy || !this.batchSelection?.has(d.mac) && (this.unsafe || !this.data.memberships_available || d.cached || d.owners.length) ? "disabled" : ""}></label>
      <button type="button" class="device-row ${this.selected === d.mac ? "selected" : ""}" data-action="select" data-id="${x(d.mac)}" aria-pressed="${this.selected === d.mac}">
      <span class="device-symbol"><ha-icon icon="${d.connection === "wired" ? "mdi:ethernet" : "mdi:wifi"}"></ha-icon></span>
      <span class="device-name"><strong>${x(d.name)}</strong><small>${x(d.ip || "No IP reported")} · ${x(connectionLabel(d.connection))}${d.band ? ` · ${x(d.band)}` : ""}</small></span>
      <span class="membership">${d.owners.length ? x(d.owners.map(id => this.profileName(id)).join(", ")) : this.data.memberships_available ? "Unassigned" : "Profile unknown"}</span>
      <span class="status ${d.online && !this.readFailed ? "online" : ""}">${this.readFailed || d.cached ? "Cached" : d.online ? "Online" : "Offline"}</span></button></div>`).join("");
  }
  deviceDetail(device) {
    const fact = (label, value) => value === undefined || value === null || value === "" ? "" :
      `<div><dt>${x(label)}</dt><dd>${x(value)}</dd></div>`;
    const fields = [
      ["IP address", device.ip], ["MAC address", device.mac], ["Connection", connectionLabel(device.connection)],
      ["Band (router label)", device.band], ["Device type (router label)", device.device_type],
      ["Signal (raw router value)", device.signal], ["Online time (raw)", device.online_time],
      ["Upload speed (raw)", device.up_speed], ["Download speed (raw)", device.down_speed],
      ["Transmit rate (raw)", device.tx_rate], ["Receive rate (raw)", device.rx_rate],
      ["Traffic usage (raw)", device.traffic_usage], ["Packets sent (count)", device.packets_sent],
      ["Packets received (count)", device.packets_received],
    ];
    const owner = device.owners[0] || "";
    const destination = this.draft.destination ?? owner;
    return `<h2 id="detail-heading" tabindex="-1">${x(device.name)}</h2>
      <p class="secondary">${device.cached || this.readFailed ? "Cached details; online status is not current." : device.online ? "Reported online in the latest poll." : "Not currently reported online."}</p>
      <dl class="facts">${fields.map(([label, value]) => fact(label, value)).join("")}</dl>
      <p class="note">${x(this.data.capabilities.telemetry_note)}</p>
      <h3>Parental profile</h3><p>${x(device.owners.length ? device.owners.map(id => this.profileName(id)).join(", ") : this.data.memberships_available ? "No parental profile" : "Profile membership unavailable")}</p>
      ${device.owners.length > 1 ? `<p role="alert">Conflicting memberships. Resolve this device in the router before editing.</p>` : ""}
      <form id="profile-change"><label>Destination profile<select id="destination" name="destination" ${this.unsafe || !this.data.memberships_available || device.owners.length > 1 ? "disabled" : ""}>
      <option value="" ${destination === "" ? "selected" : ""}>Unassigned (no profile protection)</option>
      ${this.data.profiles.map(p => `<option value="${x(p.owner_id)}" ${p.owner_id === destination ? "selected" : ""} ${!p.assignments_valid ? "disabled" : ""}>${x(p.name)}</option>`).join("")}</select></label>
      <button class="primary" ${this.unsafe || !this.data.memberships_available || device.owners.length > 1 ? "disabled" : ""}>Review profile change</button></form>
      <button type="button" data-action="new-profile" ${this.unsafe || !this.data.capabilities.create_profile ? "disabled" : ""}>Create new profile</button><p class="note">${x(this.data.capabilities.create_reason)}</p>
      ${this.reportControls(device.owners.length === 1 ? owner : "")}`;
  }
  scheduleForm(profile, period, kind) {
    const settings = profile.settings, prefix = `${period}-${kind}`;
    const flag = `enable_${period}_${kind}`;
    const title = kind === "bed_time" ? (period === "workday" ? "School nights · Sun–Thu" : "Weekend nights · Fri–Sat") :
      (period === "workday" ? "Weekday budget · Mon–Fri" : "Weekend budget · Sat–Sun");
    if (!(flag in settings)) return `<section class="rule"><h3>${title}</h3><p>Unavailable: incomplete or Pro-managed rule. No defaults have been substituted.</p></section>`;
    const enabled = this.draft[`${prefix}-enabled`] ?? settings[flag];
    const control = (name, type, value, extra = "") =>
      `<label>${name === "begin" ? "Start" : name === "end" ? "End" : "Minutes per day"}<input name="${name}" data-draft="${prefix}-${name}" type="${type}" value="${x(this.draft[`${prefix}-${name}`] ?? value)}" ${extra} ${kind === "bed_time" || enabled ? "required" : ""}></label>`;
    return `<form class="rule" data-kind="${kind}"><h3>${title}</h3><input type="hidden" name="period" value="${period}">
      <label class="check"><input type="checkbox" name="enabled" data-draft="${prefix}-enabled" ${enabled ? "checked" : ""}> Enabled</label>
      ${kind === "bed_time" ? `<div class="times">${control("begin", "time", clock(settings[`${period}_bed_time_begin`]), 'step="60"')}${control("end", "time", clock(settings[`${period}_bed_time_end`]), 'step="60"')}</div><p class="note">Router-local clock. Overnight windows are supported.</p>` :
        `${control("minutes", "number", settings[`${period}_daily_time`] || "", 'min="15" max="960" step="15"')}<p class="note">15–960 minutes, steps of 15. Zero means no budget configured; set a positive budget before enabling.</p>`}
      <button ${this.unsafe ? "disabled" : ""}>Review ${kind === "bed_time" ? "bedtime" : "budget"}</button></form>`;
  }
  profileDetail(profile) {
    return `<h2 id="detail-heading" tabindex="-1">${x(profile.name)}</h2>
      <p>${profile.internet_blocked ? "Internet manually paused" : "Manual pause cleared"} · ${profile.assignments_valid ? `${profile.members.length} assigned devices` : "Assignments unavailable"}</p>
      <p class="note">Schedules and content filters still apply when manual pause is cleared.</p>
      <form id="rename-profile"><label>Profile name<input id="profileName" name="profileName" required maxlength="64" value="${x(this.draft.profileName ?? profile.name)}"></label><button ${this.unsafe || !profile.assignments_valid ? "disabled" : ""}>Review rename</button></form>
      <button id="delete-profile" type="button" class="danger" data-action="delete-profile" ${this.unsafe || !profile.assignments_valid ? "disabled" : ""}>${this.featureLoading === "delete_preview" ? "Loading deletion preview…" : "Review delete profile"}</button>
      ${this.featureErrorKind === "delete_preview" ? `<p role="alert">${x(this.featureError)}</p>` : ""}
      <p class="note">Deleting removes this profile's filters and schedules and releases all its devices. Review a fresh affected-device list before confirming.</p>
      <form id="profile-access"><label class="check"><input id="access-enabled" type="checkbox" name="enabled" ${(this.draft.accessEnabled ?? !profile.internet_blocked) ? "checked" : ""}> Internet access (manual pause only)</label><button ${this.unsafe ? "disabled" : ""}>Review internet access</button></form>
      <h3>Assigned devices</h3>${profile.assignments_valid ? `<ul>${profile.members.map(mac => {
        const device = this.data.devices.find(d => d.mac === mac);
        return `<li><button type="button" class="device-link" data-action="open-device" data-id="${x(mac)}">${x(device?.name || mac)} · ${device?.online && !this.readFailed ? "Online" : device?.cached || this.readFailed ? "Cached" : "Offline"}</button></li>`;
      }).join("") || "<li>No devices assigned</li>"}</ul>` : '<p role="alert">Assignment list unavailable; refresh before editing.</p>'}
      ${["time_limit", "bed_time"].map(kind => ["workday", "weekend"].map(period => this.scheduleForm(profile, period, kind)).join("")).join("")}
      ${this.reportControls(profile.owner_id)}`;
  }
  render() {
    const focused = this.shadowRoot.activeElement;
    const focusKey = focused?.id || focused?.dataset.draft || focused?.dataset.filter;
    const selection = focused && ["text", "search"].includes(focused.type) ? focused.selectionStart : null;
    const data = this.data;
    if (data && !data.memberships_available) this.filters.profile = "all";
    const device = this.tab === "devices" && data?.devices.find(d => d.mac === this.selected);
    const profile = this.tab === "profiles" && data?.profiles.find(p => p.owner_id === this.selected);
    const options = (values, selected) => values.map(([value, label]) => `<option value="${x(value)}" ${value === selected ? "selected" : ""}>${x(label)}</option>`).join("");
    const status = !data ? "Loading latest network snapshot…" : this.readFailed ? "Connection failed · showing cached data" :
      !data.available ? "Router unavailable · cached data" : data.paused ? "Router polling paused · cached data" :
      data.stale ? "Snapshot stale · cached data" : `Latest poll ${Math.max(0, Math.floor((Date.now() - Date.parse(data.updated_at)) / 1000))} seconds ago`;
    this.shadowRoot.innerHTML = `<style>${styles}</style>
      <!-- THESIS: Current connections before historical inventory. OWN-WORLD: HA theme tokens and native controls.
      STORY: Scan, inspect, review a change, verify read-back. FIRST VIEWPORT: searchable master list with inline details.
      FORM: Brief-pinned Operate workspace; no independent visual identity or decorative dashboard. -->
      <header><button type="button" class="menu" data-action="menu" aria-label="Open sidebar"><ha-icon icon="mdi:menu"></ha-icon></button><h1>Network &amp; parental controls</h1><button type="button" data-action="refresh" ${this.busy || !data ? "disabled" : ""}>${this.busy ? "Working…" : "Refresh router"}</button></header>
      <main aria-busy="${this.loading || this.busy}">
      ${this.routers?.length > 1 ? `<label class="router-label">Router<select id="router" ${this.busy ? "disabled" : ""}>${this.routers.map(r => `<option value="${x(r.entry_id)}" ${r.entry_id === this.entryId ? "selected" : ""}>${x(r.name)}</option>`).join("")}</select></label>` : ""}
      <p class="freshness" role="status">${x(status)}</p>
      ${data && !data.memberships_available ? '<p class="note" role="status">Profile memberships are unavailable or incomplete. Unknown ownership is not labeled unassigned; profile filters and assignment changes are unavailable.</p>' : ""}
      ${this.error ? `<div class="error" role="alert">${x(this.error)} <button type="button" data-action="retry">Retry read</button></div>` : ""}
      ${this.notice ? `<p class="notice" role="status">${x(this.notice)}</p>` : ""}
      ${this.batchResults()}
      <nav aria-label="Workspace"><button type="button" data-action="tab" data-tab="devices" aria-current="${this.tab === "devices" ? "page" : "false"}">Devices</button><button type="button" data-action="tab" data-tab="profiles" aria-current="${this.tab === "profiles" ? "page" : "false"}">Parental profiles</button></nav>
      ${data ? `${this.tab === "profiles" ? `<button type="button" data-action="new-profile" ${this.unsafe || !data.capabilities.create_profile ? "disabled" : ""}>Create new profile</button>${this.creationForm()}` : ""}${this.tab === "devices" ? `<div class="filters">
        <label class="search">Search devices<input id="search" data-filter="search" type="search" placeholder="Name, IP, MAC or profile" value="${x(this.filters.search)}"></label>
        <label>State<select data-filter="status">${options([["online", "Online"], ["offline", "Offline / cached"], ["all", "All states"]], this.filters.status)}</select></label>
        <label>Connection<select data-filter="connection">${options([["wifi", "Wi-Fi (main + guest)"], ["host", "Main Wi-Fi"], ["guest", "Guest Wi-Fi"], ["wired", "Wired"], ["unknown", "Unknown"], ["all", "All connections"]], this.filters.connection)}</select></label>
        <label>Profile<select data-filter="profile" ${!data.memberships_available ? "disabled" : ""}>${options([["all", "All profiles"], ["none", "Unassigned"], ...data.profiles.map(p => [p.owner_id, p.name])], this.filters.profile)}</select></label>
        </div><section id="batch-controls" aria-label="Assign selected devices">${this.batchControls()}</section>` : ""}
        <div class="workspace ${device || profile ? "with-detail" : ""}"><section class="list" aria-label="${this.tab === "devices" ? "Devices" : "Profiles"}">
        ${this.tab === "devices" ? `<h2 id="result-count">${filterDevices(data, this.filters).length} devices</h2><div id="device-list">${this.deviceRows()}</div>` : `<h2>${data.profiles.length} profiles</h2>
        ${!data.profiles_available ? '<div class="empty"><h3>Profiles unavailable</h3><p>This router does not support the inspected HomeCare API or its latest read failed. No profile writes are enabled.</p></div>' : data.profiles.map(p => `<button type="button" class="device-row" data-action="select" data-id="${x(p.owner_id)}"><span class="device-name"><strong>${x(p.name)}</strong><small>${p.assignments_valid ? `${p.members.length} devices` : "Assignments unavailable"}</small></span><span>${p.internet_blocked ? "Paused" : "Pause cleared"}</span></button>`).join("") || '<p class="empty">No profiles yet. Load creation options to add an empty profile.</p>'}`}
        </section>${device || profile ? `<aside aria-label="Details"><button class="close" type="button" data-action="close">Close details</button>${device ? this.deviceDetail(device) : this.profileDetail(profile)}</aside>` : ""}</div>` :
        `<div class="empty"><h2>${this.loading ? "Loading network…" : "No routers loaded"}</h2><p>${this.loading ? "Reading the integration's current snapshot." : "Configure or enable the TP-Link Router integration, then retry."}</p></div>`}
      </main><dialog aria-labelledby="confirm-title"><h2 id="confirm-title">${this.pending?.action === "delete_profile" ? "Delete parental profile?" : "Confirm profile change"}</h2><p>${x(this.confirmation)}</p>${["assign_devices", "delete_profile"].includes(this.pending?.action) ? `<ul>${(this.confirmationDevices || []).map(name => `<li>${x(name)}</li>`).join("")}</ul>` : ""}<div class="dialog-actions"><button type="button" data-action="cancel">Cancel</button><button type="button" class="${this.pending?.action === "delete_profile" ? "danger" : "primary"}" data-action="confirm">${this.pending?.action === "delete_profile" ? "Delete profile" : "Confirm change"}</button></div></dialog>`;
    this.shadowRoot.querySelector("#router")?.addEventListener("change", async e => {
      this.entryId = e.target.value; this.generation++; this.selected = null; this.draft = {};
      this.clearPrivateReport(); this.showCreate = false; this.creationOptions = null; this.creationDraft = {};
      this.batchSelection.clear(); this.batchDestination = ""; this.batchResult = null; this.pending = null;
      this.data = null; this.loading = false; await this.load();
    });
    this.shadowRoot.querySelectorAll("[data-draft]").forEach(input => input.addEventListener("input", () => {
      this.draft[input.dataset.draft] = input.type === "checkbox" ? input.checked : input.value;
    }));
    this.shadowRoot.querySelector("dialog")?.addEventListener("cancel", () => { this.pending = null; });
    if (focusKey) {
      const target = [...this.shadowRoot.querySelectorAll("input,select,button")].find(el =>
        el.id === focusKey || el.dataset.draft === focusKey || el.dataset.filter === focusKey);
      target?.focus();
      if (selection !== null && target?.setSelectionRange) target.setSelectionRange(selection, selection);
    }
    if (this.pending) this.shadowRoot.querySelector("dialog").showModal();
  }
}
const styles = `
  button.danger:not(:disabled){color:var(--error-color,#b00020);border-color:var(--error-color,#b00020)}.profile-report{margin-top:32px;border-top:1px solid var(--divider-color,#ddd);padding-top:8px}.profile-report table{width:100%;border-collapse:collapse;table-layout:fixed;margin:16px 0}.profile-report th,.profile-report td{text-align:left;vertical-align:top;padding:10px 6px;border-bottom:1px solid var(--divider-color,#ddd);overflow-wrap:anywhere}.profile-report h4{font-size:14px;margin:24px 0 12px}.profile-report [role=alert]{color:var(--error-color,#b00020)}#create-profile{max-width:720px}
  .device-item{display:flex;align-items:stretch;background:var(--card-background-color,#fff);border-bottom:1px solid var(--divider-color,#ddd)}.device-item .device-row{border-bottom:0;min-width:0}.device-check{flex:none;justify-content:center;padding:10px;cursor:pointer}.device-check input{width:24px;min-height:24px;margin:0;accent-color:var(--primary-color,#0277bd)}#batch-controls{margin-bottom:24px;border-bottom:1px solid var(--divider-color,#ddd)}.selection-summary{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.selection-summary span{font-weight:500;flex:1;min-width:130px}#batch-assign{grid-template-columns:minmax(180px,1fr) auto;align-items:end;max-width:720px}#batch-assign p{grid-column:1/-1}.batch-results{margin-bottom:24px;padding:16px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#ddd)}.batch-results li,dialog li{line-height:1.6;overflow-wrap:anywhere}dialog{max-height:calc(100vh - 32px);overflow:auto}@media(max-width:560px){#batch-assign{grid-template-columns:1fr}.selection-summary span{flex-basis:100%}.device-check{padding:10px 6px}}
  :host{display:block;color:var(--primary-text-color,#212121);background:var(--primary-background-color,#fafafa);font-family:var(--paper-font-body1_-_font-family,Roboto,Arial,sans-serif);font-size:14px;min-height:100vh}
  *{box-sizing:border-box}header{display:flex;align-items:center;gap:16px;min-height:64px;padding:8px 24px;background:var(--app-header-background-color,#03a9f4);color:var(--app-header-text-color,#fff)}h1{font-size:20px;line-height:1.4;font-weight:500;flex:1;margin:0}h2{font-size:20px;line-height:1.4;margin:0 0 16px;font-weight:500}h3{font-size:16px;margin:24px 0 12px;font-weight:500}p{line-height:1.6;max-width:72ch;margin:8px 0 16px}small,.secondary,.note,.freshness{color:var(--secondary-text-color,#616161)}small{display:block;line-height:1.5}.note{font-size:13px}.freshness{margin:0 0 16px}
  main{padding:24px;max-width:1600px;margin:auto}button,input,select{font:inherit}button{cursor:pointer;min-height:44px;padding:10px 16px;color:var(--primary-color,#0277bd);background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#d0d0d0);border-radius:4px}button:hover{background:var(--secondary-background-color,#eee)}button:active{filter:brightness(.94)}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--primary-color,#0277bd);outline-offset:3px}button:disabled{color:var(--disabled-text-color,#757575);background:var(--secondary-background-color,#eee);cursor:not-allowed}button.primary{background:var(--primary-color,#0277bd);color:var(--text-primary-color,#fff);border-color:transparent}.primary:hover{filter:brightness(.9)}header button{border:0}.menu{background:transparent;color:inherit;padding:8px}ha-icon{width:24px;height:24px}
  nav{display:flex;gap:8px;border-bottom:1px solid var(--divider-color,#ddd);margin-bottom:24px;padding-bottom:8px}nav button{background:transparent;border:0}nav [aria-current=page]{font-weight:600;box-shadow:0 2px var(--primary-color,#0277bd)}label{display:flex;flex-direction:column;gap:8px;font-size:13px;font-weight:500}input,select{min-height:44px;max-width:100%;padding:10px 12px;border:1px solid var(--divider-color,#aaa);border-radius:4px;color:var(--primary-text-color,#212121);background:var(--card-background-color,#fff)}.filters{display:grid;grid-template-columns: minmax(200px,2fr) repeat(3,minmax(140px,1fr));gap:16px;margin-bottom:24px}.workspace{display:grid;grid-template-columns:minmax(0,1fr);gap:24px}.workspace.with-detail{grid-template-columns:minmax(0,1.3fr) minmax(340px,1fr)}.list{min-width:0}.device-row{width:100%;display:flex;align-items:center;text-align:left;gap:16px;padding:16px;border:0;border-bottom:1px solid var(--divider-color,#ddd);border-radius:0;color:inherit;background:var(--card-background-color,#fff)}.device-row.selected{background:var(--secondary-background-color,#eee);box-shadow:inset 0 0 0 2px var(--primary-color,#0277bd)}.device-symbol{color:var(--secondary-text-color,#616161)}.device-name{flex:1;min-width:0;overflow-wrap:anywhere}.membership{max-width:25%;overflow-wrap:anywhere;color:var(--secondary-text-color,#616161)}.status{font-size:13px}.status.online{color:var(--success-color,#1b6e29)}aside{min-width:0;background:var(--card-background-color,#fff);padding:24px;align-self:start;border:1px solid var(--divider-color,#ddd);border-radius:4px;overflow-wrap:anywhere}.close{float:right;margin:0 0 12px 12px}.facts{margin:24px 0}.facts div{display:grid;grid-template-columns:1fr 1fr;gap:16px;border-bottom:1px solid var(--divider-color,#ddd);padding:10px 0}.facts dt{color:var(--secondary-text-color,#616161)}dd{margin:0;overflow-wrap:anywhere}form{display:grid;gap:16px;margin-bottom:24px}.rule{padding-top:8px;border-top:1px solid var(--divider-color,#ddd);margin-top:24px}.rule h3{margin:12px 0}.check{flex-direction:row;align-items:center}.check input{min-height:24px;width:24px;accent-color:var(--primary-color,#0277bd)}.times{display:grid;grid-template-columns:1fr 1fr;gap:16px}.empty{padding:32px 16px}.empty h3{margin-top:0}.error,.notice{padding:16px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#ddd);margin-bottom:16px}.error{color:var(--error-color,#b00020)}.router-label{max-width:360px;margin-bottom:16px}dialog{border:1px solid var(--divider-color,#ddd);border-radius:8px;padding:24px;max-width:540px;width:calc(100% - 32px);color:var(--primary-text-color,#212121);background:var(--card-background-color,#fff);box-shadow:0 12px 32px #0004}dialog::backdrop{background:#0007}.dialog-actions{display:flex;justify-content:flex-end;gap:12px;margin-top:24px}
  @media(max-width:1000px){.filters{grid-template-columns:1fr 1fr}.workspace.with-detail{grid-template-columns:1fr}aside{grid-row:1}.membership{display:none}}@media(max-width:560px){main{padding:16px}header{padding:8px 12px;gap:8px}h1{font-size:18px}header button{padding:8px}.filters{grid-template-columns:1fr 1fr;gap:12px}.search{grid-column:1/-1}.filters label:last-child{grid-column:1/-1}.device-row{padding:16px 8px;gap:12px}.device-symbol{display:none}aside{padding:16px}.times{grid-template-columns:1fr 1fr}.facts div{grid-template-columns:1fr;gap:6px}}@media(prefers-reduced-motion:no-preference){button{transition:background-color .15s ease-out}}`;
if (!customElements.get("tplink-network-panel")) customElements.define("tplink-network-panel", TPLinkNetworkPanel);
