(function startAgentBridgeContent() {
  "use strict";

  const Core = globalThis.AgentBridgeCore;
  const Chat = globalThis.AgentBridgeChatGPT;
  const state = {
    armed: false,
    busy: false,
    sessionId: null,
    stepCount: 0,
    processed: new Set(),
    retryAfter: new Map()
  };

  function randomSessionId() {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    const suffix = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    return `AB-${Date.now().toString(36)}-${suffix}`;
  }

  async function config() {
    return Object.assign({
      autoSend: true,
      maxSteps: 10,
      pollMilliseconds: 1000,
      jobTimeoutSeconds: 1800
    }, await chrome.storage.sync.get(["autoSend", "maxSteps", "pollMilliseconds", "jobTimeoutSeconds"]));
  }

  function gateway(method, path, body) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "agentbridge.gateway", method, path, body }, (reply) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!reply || !reply.ok) {
          reject(new Error(reply && reply.error ? reply.error : "gateway request failed"));
        } else {
          resolve(reply.response);
        }
      });
    });
  }

  function controls() {
    let root = document.getElementById("agentbridge-controls");
    if (root) return root;
    root = document.createElement("aside");
    root.id = "agentbridge-controls";
    root.setAttribute("aria-label", "AgentBridge controls");
    root.innerHTML = `
      <style>
        #agentbridge-controls{position:fixed;right:16px;bottom:84px;z-index:2147483647;background:#111827;color:#f9fafb;border:1px solid #374151;border-radius:12px;padding:10px 12px;font:12px/1.4 system-ui;box-shadow:0 8px 24px #0004;max-width:260px}
        #agentbridge-controls button{background:#10a37f;color:white;border:0;border-radius:8px;padding:6px 10px;cursor:pointer;font-weight:600}
        #agentbridge-controls button[data-action="options"]{background:#374151;margin-left:6px}
        #agentbridge-status{display:block;margin-top:6px;color:#d1d5db;overflow-wrap:anywhere}
      </style>
      <button type="button" data-action="arm">连接 AgentBridge</button>
      <button type="button" data-action="options">设置</button>
      <span id="agentbridge-status">未连接</span>`;
    root.querySelector('[data-action="arm"]').addEventListener("click", toggleArm);
    root.querySelector('[data-action="options"]').addEventListener("click", () => chrome.runtime.openOptionsPage());
    document.documentElement.appendChild(root);
    return root;
  }

  function setStatus(text, isError = false) {
    const target = controls().querySelector("#agentbridge-status");
    target.textContent = text;
    target.style.color = isError ? "#fca5a5" : "#d1d5db";
    const button = controls().querySelector('[data-action="arm"]');
    button.textContent = state.armed ? "断开 AgentBridge" : "连接 AgentBridge";
  }

  async function toggleArm() {
    if (state.armed) {
      state.armed = false;
      state.sessionId = null;
      setStatus("已断开");
      return;
    }
    try {
      setStatus("检查本地网关…");
      const health = await gateway("GET", "/health");
      if (!health.ok) throw new Error(health.body && health.body.error || `HTTP ${health.status}`);
      state.sessionId = randomSessionId();
      state.stepCount = 0;
      state.processed.clear();
      state.armed = true;
      const promptResponse = await fetch(chrome.runtime.getURL("brain-prompt.txt"));
      const promptTemplate = await promptResponse.text();
      const prompt = promptTemplate.replaceAll("{{SESSION_ID}}", state.sessionId);
      const current = await config();
      await Chat.insertAndMaybeSend(document, prompt, current.autoSend);
      setStatus(`已连接 · 0/${current.maxSteps} 轮`);
    } catch (error) {
      state.armed = false;
      state.sessionId = null;
      setStatus(`连接失败：${error.message || error}`, true);
    }
  }

  function tasksFromMessage(message) {
    const tasks = [];
    for (const candidate of Chat.taskCandidates(message)) {
      if (candidate.rawJson) {
        try {
          tasks.push(Core.parseTaskJson(candidate.rawJson.trim(), state.sessionId));
        } catch (_error) {
          // A generic code block can be unrelated or still streaming.
        }
      }
      if (candidate.fencedText) {
        tasks.push(...Core.extractFencedTasks(candidate.fencedText, state.sessionId));
      }
    }
    return tasks;
  }

  function requireArmed(sessionId) {
    if (!state.armed || state.sessionId !== sessionId) {
      const error = new Error("bridge was disconnected");
      error.agentBridgeDisconnected = true;
      throw error;
    }
  }

  async function pollJob(jobId, current, sessionId) {
    const deadline = Date.now() + current.jobTimeoutSeconds * 1000;
    while (Date.now() < deadline) {
      requireArmed(sessionId);
      const reply = await gateway("GET", `/v1/jobs/${jobId}`);
      if (!reply.ok) throw new Error(reply.body && reply.body.error || `HTTP ${reply.status}`);
      if (Core.isTerminalJob(reply.body)) return reply.body;
      await new Promise((resolve) => setTimeout(resolve, current.pollMilliseconds));
    }
    throw new Error("local bridge job polling timed out");
  }

  async function handleTask(task) {
    const key = Core.taskKey(task);
    if (state.processed.has(key) || state.busy) return;
    const retryAt = state.retryAfter.get(key) || 0;
    if (Date.now() < retryAt) return;
    const current = await config();
    if (state.stepCount >= current.maxSteps) {
      state.armed = false;
      setStatus(`已达到 ${current.maxSteps} 轮上限；请检查后重新连接`, true);
      return;
    }
    state.busy = true;
    setStatus(`提交第 ${state.stepCount + 1} 轮…`);
    try {
      const submitted = await gateway("POST", "/v1/jobs", task);
      if (!submitted.ok) throw new Error(submitted.body && submitted.body.error || `HTTP ${submitted.status}`);
      const job = Core.isTerminalJob(submitted.body) ? submitted.body : await pollJob(submitted.body.job_id, current, task.session_id);
      if (!job.result) throw new Error(job.error || "terminal bridge job has no result");
      requireArmed(task.session_id);
      setStatus(`回填第 ${state.stepCount + 1} 轮结果…`);
      await Chat.insertAndMaybeSend(document, Core.formatResult(job.result), current.autoSend);
      state.stepCount += 1;
      state.processed.add(key);
      if (!current.autoSend || job.result.requires_human_decision) {
        state.armed = false;
        setStatus(job.result.requires_human_decision ? "本地执行需要人工处理，已停止自动循环" : "结果已填入，自动发送关闭");
      } else {
        setStatus(`已连接 · ${state.stepCount}/${current.maxSteps} 轮`);
      }
    } catch (error) {
      if (error.agentBridgeDisconnected) {
        setStatus("已断开；本机任务可能仍在执行，结果未自动回填");
        return;
      }
      state.retryAfter.set(key, Date.now() + 5000);
      setStatus(`桥接错误，5 秒后重试：${error.message || error}`, true);
    } finally {
      state.busy = false;
    }
  }

  function scan() {
    if (!state.armed || state.busy || !state.sessionId) return;
    const messages = Chat.assistantMessages(document).reverse();
    for (const message of messages) {
      const task = tasksFromMessage(message).find((value) => !state.processed.has(Core.taskKey(value)));
      if (task) {
        void handleTask(task);
        return;
      }
    }
  }

  controls();
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  setInterval(scan, 1500);
})();
