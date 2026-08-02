"use strict";

importScripts("bridge-core.js");

const DEFAULTS = {
  gatewayUrl: "http://127.0.0.1:8765",
  token: "",
  autoSend: true,
  maxSteps: 10,
  pollMilliseconds: 1000,
  jobTimeoutSeconds: 1800
};

async function settings() {
  const synced = await chrome.storage.sync.get({
    gatewayUrl: DEFAULTS.gatewayUrl,
    autoSend: DEFAULTS.autoSend,
    maxSteps: DEFAULTS.maxSteps,
    pollMilliseconds: DEFAULTS.pollMilliseconds,
    jobTimeoutSeconds: DEFAULTS.jobTimeoutSeconds
  });
  const local = await chrome.storage.local.get({ token: "" });
  return Object.assign({}, DEFAULTS, synced, local);
}

function allowedPath(method, path) {
  if (method === "GET" && path === "/health") return true;
  if (method === "POST" && path === "/v1/jobs") return true;
  return method === "GET" && /^\/v1\/jobs\/JOB-[A-Z0-9]+$/.test(path);
}

async function gatewayRequest(message) {
  const method = message.method === "POST" ? "POST" : "GET";
  const path = String(message.path || "");
  if (!allowedPath(method, path)) throw new Error("gateway path is not allowed");
  const config = await settings();
  if (!config.token || config.token.length < 32) {
    throw new Error("Configure the AgentBridge token in extension options first");
  }
  const base = AgentBridgeCore.normalizeGatewayUrl(config.gatewayUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${base}${path}`, {
      method,
      headers: {
        "Authorization": `Bearer ${config.token}`,
        "Content-Type": "application/json"
      },
      body: method === "POST" ? JSON.stringify(message.body) : undefined,
      cache: "no-store",
      signal: controller.signal
    });
    const body = await response.json().catch(() => ({ error: "invalid_gateway_response" }));
    return { ok: response.ok, status: response.status, body };
  } finally {
    clearTimeout(timer);
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "agentbridge.gateway") return false;
  gatewayRequest(message)
    .then((response) => sendResponse({ ok: true, response }))
    .catch((error) => sendResponse({ ok: false, error: String(error.message || error) }));
  return true;
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason !== "install") return;
  const config = await settings();
  if (!config.token) chrome.runtime.openOptionsPage();
});
