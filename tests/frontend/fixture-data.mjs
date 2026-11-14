// Synthetic documentation-range addresses only. Never load household data here.
export function fixture() {
  const devices = [
    { mac: "02:00:00:00:00:01", name: "Study laptop", ip: "192.0.2.10", connection: "host", band: "5G", owners: ["0"], online: true, cached: false, signal: -48, traffic_usage: "42" },
    { mac: "02:00:00:00:00:02", name: "Guest phone", ip: "192.0.2.11", connection: "guest", band: "2.4G", owners: [], online: true, cached: false },
    { mac: "02:00:00:00:00:03", name: "Media server", ip: "192.0.2.12", connection: "wired", owners: ["1"], online: true, cached: false },
    { mac: "02:00:00:00:00:04", name: "Offline tablet", ip: "192.0.2.13", connection: "host", owners: ["0"], online: false, cached: false },
    { mac: "02:00:00:00:00:05", name: "Historical device", ip: "192.0.2.14", connection: "unknown", owners: [], online: false, cached: true },
  ];
  const settings = {};
  for (const period of ["workday", "weekend"]) {
    settings[`enable_${period}_time_limit`] = false;
    settings[`enable_${period}_bed_time`] = false;
    settings[`${period}_daily_time`] = 120;
    settings[`${period}_bed_time_begin`] = 1320;
    settings[`${period}_bed_time_end`] = 420;
  }
  return {
    entry_id: "synthetic-router", available: true, paused: false, stale: false,
    updated_at: new Date().toISOString(), profiles_available: true, memberships_available: true, devices,
    profiles: [
      { owner_id: "0", name: "Study", members: [devices[0].mac, devices[3].mac], internet_blocked: false, assignments_valid: true, settings: { ...settings } },
      { owner_id: "1", name: "Shared", members: [devices[2].mac], internet_blocked: false, assignments_valid: true, settings: { ...settings } },
      { owner_id: "2", name: "Empty profile", members: [], internet_blocked: false, assignments_valid: true, settings: { ...settings } },
    ],
    capabilities: {
      create_profile: true, reports: true,
      create_reason: "Create an empty profile, then assign devices separately.",
      reports_reason: "Profile-wide reports are loaded only on request, never stored in entity states or Recorder. No byte-usage totals.",
      telemetry_note: "Speeds, traffic and online time are raw router values. Units, period and resets are unverified; not daily or monthly totals.",
    },
  };
}
