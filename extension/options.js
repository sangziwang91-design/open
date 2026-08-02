"use strict";

const DEFAULTS = {
  gatewayUrl: "http://127.0.0.1:8765",
  token: "",
  autoSend: true,
  maxSteps: 10,
  pollMilliseconds: 1000,
  jobTimeoutSeconds: 1800
};

async function load() {
  const values = Object.assign(
    {},
    DEFAULTS,
    await chrome.storage.sync.get({
      gatewayUrl: DEFAULTS.gatewayUrl,
      autoSend: DEFAULTS.autoSend,
      maxSteps: DEFAULTS.maxSteps,
      pollMilliseconds: DEFAULTS.pollMilliseconds,
      jobTimeoutSeconds: DEFAULTS.jobTimeoutSeconds
    }),
    await chrome.storage.local.get({ token: "" })
  );
  for (const key of ["gatewayUrl", "token", "maxSteps", "pollMilliseconds", "jobTimeoutSeconds"]) {
    document.getElementById(key).value = values[key];
  }
  document.getElementById("autoSend").checked = values.autoSend;
}

document.getElementById("settings").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("status");
  try {
    const values = {
      gatewayUrl: AgentBridgeCore.normalizeGatewayUrl(document.getElementById("gatewayUrl").value),
      token: document.getElementById("token").value.trim(),
      autoSend: document.getElementById("autoSend").checked,
      maxSteps: Number(document.getElementById("maxSteps").value),
      pollMilliseconds: Number(document.getElementById("pollMilliseconds").value),
      jobTimeoutSeconds: Number(document.getElementById("jobTimeoutSeconds").value)
    };
    if (values.token.length < 32 || values.token.length > 256 || /\s/.test(values.token)) throw new Error("令牌格式无效");
    if (!Number.isInteger(values.maxSteps) || values.maxSteps < 1 || values.maxSteps > 100) throw new Error("最大轮数必须是 1-100");
    if (!Number.isInteger(values.pollMilliseconds) || values.pollMilliseconds < 250 || values.pollMilliseconds > 10000) throw new Error("轮询间隔必须是 250-10000 毫秒");
    if (!Number.isInteger(values.jobTimeoutSeconds) || values.jobTimeoutSeconds < 10 || values.jobTimeoutSeconds > 3600) throw new Error("等待上限必须是 10-3600 秒");
    const { token, ...synced } = values;
    await chrome.storage.sync.set(synced);
    await chrome.storage.local.set({ token });
    status.textContent = "已保存；请回到 ChatGPT 点击“连接 AgentBridge”。";
    status.style.color = "#047857";
  } catch (error) {
    status.textContent = `保存失败：${error.message || error}`;
    status.style.color = "#b91c1c";
  }
});

void load();
