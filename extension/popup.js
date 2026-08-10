document.getElementById("checkNow").addEventListener("click", async () => {
  const statusEl = document.getElementById("status");
  statusEl.textContent = "Checking...";
  statusEl.style.color = "";

  const response = await chrome.runtime.sendMessage({ type: "CHECK_NOW" });

  // background.js now returns a real result ({ ok: true, summary } or
  // { ok: false, error }) instead of always { ok: true } — this used to
  // show "Check complete." even when the backend request had failed or
  // timed out.
  if (response?.ok) {
    const s = response.summary;
    statusEl.style.color = "#227257";
    statusEl.textContent = s
      ? `Check complete. AQI: ${s.aqi_max ?? "n/a"}, fires nearby: ${s.fire_count}.`
      : "Check complete.";
  } else {
    statusEl.style.color = "#b3261e";
    statusEl.textContent = `Check failed: ${response?.error || "unknown error"}`;
  }
});
