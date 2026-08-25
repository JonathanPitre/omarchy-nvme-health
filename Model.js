// Pure formatting helpers for NVMe Health (no Qt).

function asInt(value, fallback) {
  var n = Number(value)
  if (!isFinite(n)) return fallback
  return Math.round(n)
}

function formatHours(hours) {
  if (hours === null || hours === undefined || !isFinite(Number(hours))) return "—"
  var h = Math.max(0, Math.round(Number(hours)))
  if (h < 24) return h + "h"
  var days = Math.floor(h / 24)
  var rem = h % 24
  return days + "d " + rem + "h"
}

function formatTiB(value) {
  if (value === null || value === undefined || !isFinite(Number(value))) return "—"
  var n = Number(value)
  if (n < 0.1) return n.toFixed(2) + " TiB"
  if (n < 10) return n.toFixed(1) + " TiB"
  return Math.round(n) + " TiB"
}

function formatPercent(value) {
  if (value === null || value === undefined || !isFinite(Number(value))) return "—"
  return Math.round(Number(value)) + "%"
}

function barLabel(disk, needsSetup, missingSmartctl) {
  if (missingSmartctl) return "?"
  if (needsSetup) return "!"
  if (!disk) return "—"
  if (disk.warning) return "!"
  if (disk.lifeRemainingPercent === null || disk.lifeRemainingPercent === undefined)
    return "OK"
  return Math.round(Number(disk.lifeRemainingPercent)) + "%"
}

function parseStatus(text) {
  try {
    var data = JSON.parse(String(text || ""))
    if (!data || typeof data !== "object") return null
    return data
  } catch (e) {
    return null
  }
}

if (typeof module !== "undefined") {
  module.exports = {
    asInt: asInt,
    formatHours: formatHours,
    formatTiB: formatTiB,
    formatPercent: formatPercent,
    barLabel: barLabel,
    parseStatus: parseStatus
  }
}
