import test from "node:test";
import assert from "node:assert/strict";
import { fixture } from "./fixture-data.mjs";

globalThis.HTMLElement = class {};
globalThis.customElements = { get() {}, define() {} };
const { filterDevices, batchSelectionError, escape, TPLinkNetworkPanel } = await import("../../custom_components/tplink_router/frontend/network-panel.js");
const defaults = { search: "", status: "online", connection: "wifi", profile: "all" };

test("Online Wi-Fi default excludes wired, offline and cached devices", () => {
  assert.deepEqual(filterDevices(fixture(), defaults).map(d => d.name), ["Guest phone", "Study laptop"]);
  const data = fixture();
  data.devices[0].cached = true; // Even a historical home-like flag cannot make a cached device online.
  assert.equal(filterDevices(data, defaults).length, 1);
});
test("Search uses friendly profile, device name, IP and MAC without case sensitivity", () => {
  for (const search of ["STUDY", "192.0.2.10", "02:00:00:00:00:01", "  laptop  "]) {
    assert.equal(filterDevices(fixture(), { ...defaults, search })[0].name, "Study laptop");
  }
});
test("Connection, profile and state filters support unassigned, empty and offline profiles", () => {
  assert.equal(filterDevices(fixture(), { ...defaults, profile: "none" })[0].name, "Guest phone");
  assert.equal(filterDevices(fixture(), { ...defaults, profile: "2" }).length, 0);
  assert.equal(filterDevices(fixture(), { ...defaults, connection: "wired" })[0].name, "Media server");
  assert.equal(filterDevices(fixture(), { ...defaults, status: "offline", connection: "all" }).length, 2);
});
test("Household-supplied values are escaped, never executable markup", () => {
  assert.equal(escape(`<img onerror="x">&'`), "&lt;img onerror=&quot;x&quot;&gt;&amp;&#39;");
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  panel.data = fixture(); panel.draft = {};
  const device = { ...panel.data.devices[0], name: "<script>alert(1)</script>" };
  const html = panel.deviceDetail(device);
  assert.ok(html.includes("&lt;script&gt;")); assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("Traffic usage (raw)")); assert.ok(!html.includes("GB"));
});
test("Budget and bedtime forms preserve units, disabled zero sentinel and nightly semantics", () => {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  panel.data = fixture(); panel.draft = {};
  const profile = panel.data.profiles[0];
  profile.settings.workday_daily_time = 0;
  const budget = panel.scheduleForm(profile, "workday", "time_limit");
  assert.ok(budget.includes('min="15" max="960" step="15"'));
  assert.ok(budget.includes('value=""')); assert.ok(!budget.includes(" required"));
  assert.ok(panel.scheduleForm(profile, "workday", "bed_time").includes("Sun–Thu"));
  assert.ok(panel.scheduleForm(profile, "weekend", "bed_time").includes("Fri–Sat"));
  profile.settings = {};
  assert.ok(panel.scheduleForm(profile, "workday", "time_limit").includes("No defaults"));
});
test("Stale, failed, paused and unsupported snapshots disable mutation controls", () => {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  for (const field of ["stale", "paused"]) {
    panel.data = { ...fixture(), [field]: true };
    assert.ok(panel.unsafe);
  }
  panel.data = { ...fixture(), profiles_available: false }; assert.ok(panel.unsafe);
  panel.data = fixture(); panel.readFailed = true; assert.ok(panel.unsafe);
});
test("Unavailable memberships are unknown, never successful empty/unassigned results", () => {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  panel.data = { ...fixture(), memberships_available: false }; panel.draft = {};
  assert.equal(filterDevices(panel.data, { ...defaults, profile: "none" }).length, 0);
  const html = panel.deviceDetail(panel.data.devices[1]);
  assert.ok(html.includes("Profile membership unavailable"));
  assert.ok(html.includes('class="primary" disabled'));
});
test("Batch selection excludes assigned, missing and cached devices, and detects duplicates", () => {
  const data = fixture(), unassigned = data.devices[1].mac;
  assert.equal(batchSelectionError(data, [unassigned]), "");
  for (const macs of [[], [unassigned, unassigned], [data.devices[0].mac], [data.devices[4].mac], ["missing"]]) {
    assert.ok(batchSelectionError(data, macs));
  }
  data.memberships_available = false;
  assert.ok(batchSelectionError(data, [unassigned]).includes("unavailable"));
});
test("Batch toolbar names hidden selection counts and explicit destination without authorizing moves", () => {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  panel.data = fixture(); panel.filters = { ...defaults, search: "laptop" };
  panel.batchSelection = new Set([panel.data.devices[1].mac]);
  panel.batchDestination = "2";
  const html = panel.batchControls();
  assert.ok(html.includes("1 selected · 1 hidden by filters"));
  assert.ok(html.includes("Review 1 assignments"));
  assert.ok(html.includes("individual review for explicit moves"));
  assert.ok(html.includes('value="2" selected'));
  panel.data.devices[1].owners = ["0"];
  assert.ok(panel.batchControls().includes("now assigned"));
});
test("Aging confirmation becomes unsafe even without another snapshot", () => {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  panel.data = fixture();
  panel.data.updated_at = new Date(Date.now() - 121000).toISOString();
  assert.ok(panel.unsafe);
});
test("Batch results never label applied-but-unconfirmed or partial results as blanket success", async () => {
  for (const status of ["assigned", "assigned_unconfirmed", "not_assigned", "conflict", "unknown"]) {
    const panel = Object.create(TPLinkNetworkPanel.prototype);
    panel.data = fixture(); panel.render = () => {}; panel.draft = {};
    const mac = panel.data.devices[1].mac;
    panel.batchSelection = new Set([mac]);
    panel.entryId = "synthetic-router";
    let calls = 0;
    panel._hass = { async callWS() {
      calls++;
      return { ...fixture(), assignment_result: {
        confirmed: status === "assigned", error: status === "assigned" ? null : "Unconfirmed",
        outcomes: [{ mac, status }],
      } };
    } };
    await panel.execute({ action: "assign_devices", macs: [mac], destination: "2" }, "");
    assert.equal(calls, 1);
    assert.equal(panel.batchSelection.size, 0);
    assert.equal(Boolean(panel.notice), status === "assigned");
    assert.equal(Boolean(panel.error), status !== "assigned");
    assert.ok(panel.batchResults().includes("No automatic retry"));
  }
});
test("Lost/malformed batch responses produce unknown outcomes and read-only recovery, never a retry", async () => {
  for (const failure of ["transport", "missing", "wrong-identities"]) {
    const panel = Object.create(TPLinkNetworkPanel.prototype);
    panel.data = fixture(); panel.render = () => {};
    const mac = panel.data.devices[1].mac;
    panel.batchSelection = new Set([mac]); panel.entryId = "synthetic-router";
    const calls = [];
    panel._hass = { async callWS(request) {
      calls.push(request);
      if (request.type === "tplink_router/network") return fixture();
      if (failure === "transport") throw new Error("Connection lost");
      return { ...fixture(), assignment_result: failure === "missing" ? null : {
        confirmed: true, outcomes: [{ mac: "wrong", status: "assigned" }],
      } };
    } };
    await panel.execute({ action: "assign_devices", macs: [mac], destination: "2" }, "");
    assert.equal(calls.filter(c => c.type === "tplink_router/network_action").length, 1);
    assert.equal(calls.filter(c => c.type === "tplink_router/network").length, 1);
    assert.equal(panel.batchResult.outcomes[0].status, "unknown");
    assert.equal(panel.batchSelection.size, 0);
    assert.ok(panel.error); assert.equal(panel.notice, "");
  }
});
test("A quiet read already in flight cannot overwrite authoritative batch action results", async () => {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  panel.data = fixture(); panel.render = () => {}; panel.generation = 0;
  const mac = panel.data.devices[1].mac;
  panel.batchSelection = new Set([mac]); panel.entryId = "synthetic-router"; panel.routers = [];
  let releaseRead;
  panel._hass = { async callWS(request) {
    if (request.type === "tplink_router/network") return new Promise(resolve => { releaseRead = resolve; });
    const data = fixture();
    data.devices[1].owners = ["2"];
    return { ...data, assignment_result: {
      confirmed: true, error: null, outcomes: [{ mac, status: "assigned" }],
    } };
  } };
  const read = panel.load(true);
  await panel.execute({ action: "assign_devices", macs: [mac], destination: "2" }, "");
  releaseRead(fixture());
  await read;
  assert.deepEqual(panel.data.devices[1].owners, ["2"]);
  assert.ok(panel.notice.includes("confirmed"));
});
function featurePanel() {
  const panel = Object.create(TPLinkNetworkPanel.prototype);
  Object.assign(panel, {
    data: fixture(), draft: {}, creationDraft: {}, featureGeneration: 0, generation: 0,
    entryId: "synthetic-router", batchSelection: new Set(), render() {},
  });
  return panel;
}
test("Private report loads explicitly, is not attached to network data, and clears on leaving", async () => {
  const panel = featurePanel();
  panel._hass = { callWS: async request => ({
    owner_id: request.owner_id, insights: { status: "ok", data: [] }, history: { status: "ok", data: [] },
  }) };
  await panel.loadFeature("report", "0");
  assert.equal(panel.report.owner_id, "0");
  assert.equal(panel.data.report, undefined);
  assert.ok(panel.reportControls("0").includes("No daily records returned"));
  panel.clearPrivateReport();
  assert.equal(panel.report, null);
});
test("Report response arriving after navigation is discarded instead of revealing private history", async () => {
  const panel = featurePanel();
  let release;
  panel._hass = { callWS: () => new Promise(resolve => { release = resolve; }) };
  const read = panel.loadFeature("report", "0");
  panel.clearPrivateReport();
  release({ owner_id: "0", insights: { status: "ok", data: [] }, history: { status: "ok", data: [] } });
  await read;
  assert.equal(panel.report, null);
  assert.equal(panel.featureLoading, "");
});
test("Report errors are distinct from empty, wrong-owner responses rejected, and sites never become links/markup", async () => {
  const panel = featurePanel();
  panel._hass = { callWS: async () => ({ owner_id: "wrong", insights: {}, history: {} }) };
  await panel.loadFeature("report", "0");
  assert.equal(panel.report, null); assert.ok(panel.featureError.includes("incomplete"));
  panel.report = {
    owner_id: "0", insights: { status: "ok", data: [{ minutes: 1, websites: [
      { website: "<img onerror=alert(1)>", minutes: 1, blocked: false },
    ] }] }, history: { status: "unavailable", error: "History unavailable" },
  };
  const html = panel.reportControls("0");
  assert.ok(html.includes("&lt;img")); assert.ok(!html.includes("<img") && !html.includes("href="));
  assert.ok(html.includes("History unavailable")); assert.ok(!html.includes("No history records returned"));
});
test("Creation options are explicit, escaped and never auto-selected or granted implicit assignment", async () => {
  const panel = featurePanel();
  panel.showCreate = true;
  panel._hass = { callWS: async () => ({
    maximum: 16, remaining: 0, presets: [{ filter_level: "teen", categories: ["<script>"] }],
  }) };
  await panel.loadFeature("creation_options");
  panel.creationDraft = { newName: "<example>", newFilter: "teen" };
  const html = panel.creationForm();
  assert.ok(html.includes("0 profile slots"));
  assert.ok(html.includes("&lt;example&gt;") && html.includes("&lt;script&gt;"));
  assert.ok(html.includes("Review new profile</button>") && html.includes("class=\"primary\" disabled"));
  assert.ok(html.includes("assign devices separately"));
});
test("Unconfirmed creation closes submitted form and never claims success or retries", async () => {
  const panel = featurePanel(), calls = [];
  panel.showCreate = true;
  panel._hass = { callWS: async request => {
    calls.push(request);
    return { ...fixture(), creation_result: { confirmed: false, error: "Unconfirmed; inspect actual profiles" } };
  } };
  await panel.execute({ action: "create_profile", name: "Example", filter_level: "adult", categories: [] }, "");
  assert.ok(panel.error.includes("Unconfirmed"));
  assert.equal(panel.showCreate, false);
  assert.equal(panel.notice, "");
  assert.equal(calls.length, 1);
});
test("Deletion preview carries fresh revision and affected devices; no deletion request is sent by preview", async () => {
  const panel = featurePanel(), calls = [];
  panel._hass = { callWS: async request => {
    calls.push(request);
    return { owner_id: "0", name: "Study", members: [panel.data.devices[0].mac], revision: "a".repeat(64) };
  } };
  await panel.loadFeature("delete_preview", "0");
  assert.equal(panel.pending.action, "delete_profile");
  assert.equal(panel.pending.revision, "a".repeat(64));
  assert.deepEqual(panel.confirmationDevices, ["Study laptop"]);
  assert.ok(panel.confirmation.includes("1 assigned devices") && panel.confirmation.includes("lose this profile"));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].type, "tplink_router/profile_read");
});
test("Stale snapshots cannot load new reports, metadata or deletion previews", async () => {
  const panel = featurePanel();
  panel.data.stale = true;
  panel._hass = { callWS() { throw new Error("Must not contact router"); } };
  for (const kind of ["report", "creation_options", "delete_preview"]) await panel.loadFeature(kind, "0");
  assert.equal(panel.report, undefined);
  assert.equal(panel.pending, undefined);
});
