// background.js — Manifest V3 service worker.
//
// IMPORTANT MV3 REALITY: this file does NOT run continuously. Chrome
// suspends the service worker after ~30s of inactivity and restarts it
// only to handle a registered event (alarms, messages, install). There is
// no persistent "while(true) monitor" here by design — chrome.alarms is
// the MV3-native replacement for that pattern. Every function below must
// assume it could be the first thing run after a cold start: don't rely
// on in-memory state surviving between alarm firings, use chrome.storage
// instead.

const BACKEND_BASE = "http://localhost:8000"; // same FastAPI backend as the
// main GaiaNet app — /alerts/summary was added to backend/main.py and
// backend/services/alerts.py. Change to your deployed domain once hosted.
const ALARM_NAME = "planetary-health-check";
const CHECK_INTERVAL_MINUTES = 15; // stay well above API rate-limit floors
const AQI_ALERT_THRESHOLD = 200;
// Was 8000ms, tuned for a fetch that should return a tiny payload fast.
// The actual slow part was backend-side (see backend/services/alerts.py
// and openaq_client.get_stations_near — the old global 100-station sweep
// is now a targeted radius query), so this no longer needs to be huge,
// but a cold OpenAQ/FIRMS upstream call plus normal network variance can
// still legitimately take more than 8s. 15s gives real headroom without
// letting a single tick hang indefinitely.
const FETCH_TIMEOUT_MS = 15000;

// ---- Lifecycle: register the alarm once, on install/update ----
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM_NAME, {
    periodInMinutes: CHECK_INTERVAL_MINUTES,
  });
  console.log(`[PlanetaryHealthOS] Alarm registered: every ${CHECK_INTERVAL_MINUTES}min`);
});

// Also re-arm on browser startup — alarms can be dropped across restarts
// on some platforms, and this is cheap insurance.
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.get(ALARM_NAME, (existing) => {
    if (!existing) {
      chrome.alarms.create(ALARM_NAME, { periodInMinutes: CHECK_INTERVAL_MINUTES });
    }
  });
});

// ---- The actual "monitoring" — runs once per alarm tick ----
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    runThreatCheck()
      .then((result) => {
        if (!result.ok) {
          console.warn("[PlanetaryHealthOS] Alarm-triggered check did not complete:", result.error);
        }
      })
      .catch((err) =>
        console.error("[PlanetaryHealthOS] Threat check threw unexpectedly:", err)
      );
  }
});

async function runThreatCheck() {
  const location = await getMonitoredLocation();
  if (!location) {
    return { ok: false, error: "No monitored location set yet." };
  }

  const { summary, error } = await fetchAlertSummary(location);
  if (!summary) {
    // Backend unreachable/errored this tick — surfaced to the caller
    // (popup) instead of silently swallowed. The alarm-driven path just
    // logs and tries again next tick; that behavior is unchanged.
    return { ok: false, error: error || "Backend unreachable." };
  }

  const previouslyAlerted = await getLastAlertState();

  if (summary.aqi_max >= AQI_ALERT_THRESHOLD && !previouslyAlerted.aqi) {
    notify(
      "airQualityAlert",
      "Air Quality Alert",
      `AQI has reached ${summary.aqi_max} near your monitored location.`
    );
  }

  if (summary.fire_cluster_detected && !previouslyAlerted.fire) {
    notify(
      "wildfireAlert",
      "Wildfire Cluster Detected",
      `Active fire cluster detected within your monitored radius.`
    );
  }

  // Persist state so we don't re-notify every 15 minutes for the same
  // ongoing event — only on threshold transitions (below -> above).
  await chrome.storage.local.set({
    lastAlertState: {
      aqi: summary.aqi_max >= AQI_ALERT_THRESHOLD,
      fire: !!summary.fire_cluster_detected,
      lastChecked: Date.now(),
    },
  });

  return { ok: true, summary };
}

// ---- Backend call: small payload only — see architecture notes on why
// this must never be a raw FIRMS/OpenAQ fetch ----
async function fetchAlertSummary({ lat, lon, radiusKm }) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    const url = new URL(`${BACKEND_BASE}/alerts/summary`);
    url.searchParams.set("lat", lat);
    url.searchParams.set("lon", lon);
    url.searchParams.set("radius_km", radiusKm ?? 50);

    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      const message = `Backend returned ${response.status}`;
      console.warn("[PlanetaryHealthOS]", message);
      return { summary: null, error: message };
    }
    return { summary: await response.json(), error: null };
  } catch (err) {
    // AbortError specifically means our own timeout fired, not a generic
    // network failure — worth distinguishing in the message shown to the
    // person, since the fix differs (backend too slow vs. backend down).
    const message = err.name === "AbortError"
      ? `Backend didn't respond within ${FETCH_TIMEOUT_MS / 1000}s — it may be slow or unreachable.`
      : `Could not reach backend: ${err.message}`;
    console.warn("[PlanetaryHealthOS]", message);
    return { summary: null, error: message };
  } finally {
    clearTimeout(timeout);
  }
}

function notify(id, title, message) {
  chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
    priority: 2,
  });
}

async function getMonitoredLocation() {
  const { monitoredLocation } = await chrome.storage.local.get("monitoredLocation");
  return monitoredLocation ?? null;
}

async function getLastAlertState() {
  const { lastAlertState } = await chrome.storage.local.get("lastAlertState");
  return lastAlertState ?? { aqi: false, fire: false };
}

// ---- Message bridge for popup/side panel to trigger an immediate check
// or set the monitored location without waiting for the next alarm ----
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "SET_MONITORED_LOCATION") {
    chrome.storage.local.set({ monitoredLocation: message.location }).then(() => {
      runThreatCheck()
        .then(sendResponse)
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
    });
    return true; // keep the message channel open for the async response
  }
  if (message.type === "CHECK_NOW") {
    // Previously: runThreatCheck().finally(() => sendResponse({ ok: true }))
    // — that sent { ok: true } to the popup regardless of whether the
    // check actually succeeded, so a timed-out/failed backend call looked
    // identical to a real success in the UI. Now forwards runThreatCheck's
    // real result ({ ok: true, summary } or { ok: false, error }).
    runThreatCheck()
      .then(sendResponse)
      .catch((err) => sendResponse({ ok: false, error: String(err) }));
    return true;
  }
});
