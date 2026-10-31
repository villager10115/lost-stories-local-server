"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const cp = require("node:child_process");

const root = fs.mkdtempSync(path.join(os.tmpdir(), "click-comparison-"));
try {
  fs.writeFileSync(path.join(root, "events.jsonl"), [
    { time: "2026-10-20T10:00:00Z", client: "local", kind: "input", actionId: 1,
      event: "pointerdown", route: "#/Home", label: "Menu", x: 10, y: 20,
      snapshot: { route: "#/Home", loading: [], dialogs: [], brokenImages: [], controls: [], counts: { nodes: 10 } } },
    { time: "2026-10-20T10:00:01Z", client: "local", kind: "screenshot", actionId: 1,
      phase: "before", delay: 0, file: "screenshots/before.png" },
    { time: "2026-10-20T10:00:02Z", client: "local", kind: "request", actionId: 1,
      method: "GET", domain: "127.0.0.1", path: "/api/page/MyPage" },
    { time: "2026-10-20T10:00:03Z", client: "local", kind: "response", actionId: 1,
      method: "GET", domain: "127.0.0.1", path: "/api/page/MyPage", status: 200,
      remoteAddress: "127.0.0.1", remotePort: 18865, mimeType: "application/json" },
    { time: "2026-10-20T10:00:04Z", client: "local", kind: "after_input", actionId: 1,
      gesture: "1", delay: 700, route: "#/MyPage", loading: [], dialogs: [], brokenImages: [], controls: [], counts: { nodes: 20 } }
  ].map(item => JSON.stringify(item)).join("\n") + "\n");
  fs.writeFileSync(path.join(root, "native-clicks.jsonl"), [
    { time: "2026-10-20T10:00:00Z", kind: "click_down", action_id: 1, client: "official",
      screen_x: 100, screen_y: 200, client_x: 10, client_y: 20, window_title: "Game",
      window_x: 90, window_y: 180, window_width: 1000, window_height: 600 },
    { time: "2026-10-20T10:00:00.2Z", kind: "click", action_id: 1, client: "official",
      duration_ms: 200, moved: 0, client_x: 10, client_y: 20 },
    { time: "2026-10-20T10:00:00.1Z", kind: "capture", action_id: 1, client: "official",
      phase: "before", delay_ms: 0, file: "native-screenshots/before.png",
      image: { meanLuma: 50, nonBlackRatio: 0.8 }, mean_rgb_change_from_previous: null },
    { time: "2026-10-20T10:00:01.2Z", kind: "capture", action_id: 1, client: "official",
      phase: "after", delay_ms: 1200, file: "native-screenshots/after.png",
      image: { meanLuma: 60, nonBlackRatio: 0.85 }, mean_rgb_change_from_previous: 8 }
  ].map(item => JSON.stringify(item)).join("\n") + "\n");
  fs.writeFileSync(path.join(root, "network-events.jsonl"), [
    { time: "2026-10-20T10:00:00Z", kind: "tcp", client: "official", remote_address: "43.159.108.101", remote_port: 443 },
    { time: "2026-10-20T10:00:00Z", kind: "dns", name: "app.lost-stories.net", data: "43.159.108.101" }
  ].map(item => JSON.stringify(item)).join("\n") + "\n");
  cp.execFileSync(process.execPath, [path.join(__dirname, "click_comparison.js"), root], { timeout: 5000 });
  const report = JSON.parse(fs.readFileSync(path.join(root, "click-comparison.json"), "utf8"));
  if (report.actions.length !== 2) throw Error("expected two client actions");
  const official = report.actions.find(item => item.client === "official");
  const local = report.actions.find(item => item.client === "packaged-local");
  if (!official.beforeScreen || !official.afterScreens.length) throw Error("native screenshots missing");
  if (!local.before || local.requests[0].status !== 200) throw Error("local action parsing missing");
  if (!report.dnsByAddress["43.159.108.101"].includes("app.lost-stories.net")) {
    throw Error("DNS mapping missing");
  }
  console.log("click comparison contract passed");
} finally {
  const child = fs.existsSync(path.join(root, "comparison.pid"))
    ? Number(fs.readFileSync(path.join(root, "comparison.pid"), "utf8")) : null;
  if (child) {
    try { process.kill(child); } catch {}
  }
  fs.rmSync(root, { recursive: true, force: true });
}
