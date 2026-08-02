(function attachAgentBridgeCore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.AgentBridgeCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildCore() {
  "use strict";

  const PROTOCOL = "agentbridge/1";
  const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
  const TASK_KEYS = new Set([
    "protocol",
    "message_type",
    "session_id",
    "request_id",
    "parent_request_id",
    "title",
    "goal",
    "constraints",
    "acceptance",
    "timeout_seconds"
  ]);
  const ACCEPTANCE_KEYS = new Set([
    "id",
    "type",
    "command",
    "expected_exit_code",
    "rule",
    "path"
  ]);

  function exactKeys(value, allowed, label) {
    for (const key of Object.keys(value)) {
      if (!allowed.has(key)) {
        throw new Error(`${label} contains forbidden field: ${key}`);
      }
    }
  }

  function requireIdentifier(value, label) {
    if (typeof value !== "string" || !IDENTIFIER.test(value)) {
      throw new Error(`${label} is invalid`);
    }
  }

  function validateAcceptance(item) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("acceptance item must be an object");
    }
    exactKeys(item, ACCEPTANCE_KEYS, "acceptance item");
    requireIdentifier(item.id, "acceptance id");
    if (!["command", "fileexists", "gitdiff"].includes(item.type)) {
      throw new Error("acceptance type is unsupported");
    }
    if (item.type === "command" && (typeof item.command !== "string" || !item.command.trim())) {
      throw new Error("command acceptance requires command");
    }
    if (item.type === "fileexists" && (typeof item.path !== "string" || !item.path.trim())) {
      throw new Error("fileexists acceptance requires path");
    }
    if (item.type === "gitdiff" && item.rule !== undefined && !["non_empty", "empty"].includes(item.rule)) {
      throw new Error("gitdiff rule is invalid");
    }
    if (item.expected_exit_code !== undefined && !Number.isInteger(item.expected_exit_code)) {
      throw new Error("expected_exit_code must be an integer");
    }
  }

  function validateTask(task, expectedSessionId) {
    if (!task || typeof task !== "object" || Array.isArray(task)) {
      throw new Error("task must be an object");
    }
    exactKeys(task, TASK_KEYS, "task");
    if (task.protocol !== PROTOCOL || task.message_type !== "task") {
      throw new Error("protocol or message_type is invalid");
    }
    requireIdentifier(task.session_id, "session_id");
    requireIdentifier(task.request_id, "request_id");
    if (task.parent_request_id !== undefined && task.parent_request_id !== null) {
      requireIdentifier(task.parent_request_id, "parent_request_id");
    }
    if (expectedSessionId && task.session_id !== expectedSessionId) {
      throw new Error("task belongs to a different armed session");
    }
    if (typeof task.goal !== "string" || !task.goal.trim() || task.goal.length > 20000) {
      throw new Error("goal is invalid");
    }
    if (task.title !== undefined && (typeof task.title !== "string" || !task.title.trim() || task.title.length > 200)) {
      throw new Error("title is invalid");
    }
    if (task.constraints !== undefined) {
      if (!Array.isArray(task.constraints) || task.constraints.length > 32) {
        throw new Error("constraints are invalid");
      }
      for (const value of task.constraints) {
        if (typeof value !== "string" || !value.trim() || value.length > 2000) {
          throw new Error("constraint is invalid");
        }
      }
    }
    if (!Array.isArray(task.acceptance) || task.acceptance.length < 1 || task.acceptance.length > 20) {
      throw new Error("acceptance must contain 1-20 items");
    }
    task.acceptance.forEach(validateAcceptance);
    if (task.timeout_seconds !== undefined && (!Number.isInteger(task.timeout_seconds) || task.timeout_seconds < 1 || task.timeout_seconds > 3600)) {
      throw new Error("timeout_seconds is invalid");
    }
    return task;
  }

  function parseTaskJson(text, expectedSessionId) {
    return validateTask(JSON.parse(text), expectedSessionId);
  }

  function extractFencedTasks(text, expectedSessionId) {
    const tasks = [];
    const pattern = /```agentbridge-task\s*([\s\S]*?)```/gi;
    let match;
    while ((match = pattern.exec(String(text))) !== null) {
      try {
        tasks.push(parseTaskJson(match[1].trim(), expectedSessionId));
      } catch (_error) {
        // Streaming messages are often temporarily incomplete. A later DOM
        // mutation will retry the complete block.
      }
    }
    return tasks;
  }

  function taskKey(task) {
    return `${task.session_id}:${task.request_id}`;
  }

  function formatResult(result) {
    if (!result || result.protocol !== PROTOCOL || result.message_type !== "result") {
      throw new Error("gateway returned an invalid result message");
    }
    const safeJson = JSON.stringify(result, null, 2).replaceAll("```", "\\u0060\\u0060\\u0060");
    return [
      "Local AgentBridge execution evidence follows. Use its state, checks, and claim_level; do not invent unreported success.",
      "```agentbridge-result",
      safeJson,
      "```"
    ].join("\n");
  }

  function isTerminalJob(job) {
    return Boolean(job && ["FINISHED", "ERROR"].includes(job.status));
  }

  function normalizeGatewayUrl(value) {
    const url = new URL(String(value || "").trim());
    const loopback = url.hostname === "127.0.0.1" || url.hostname === "localhost";
    if (url.protocol !== "http:" || !loopback || url.username || url.password || (url.pathname !== "/" && url.pathname !== "")) {
      throw new Error("gateway URL must be an HTTP loopback origin");
    }
    url.pathname = "";
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  }

  return {
    PROTOCOL,
    extractFencedTasks,
    formatResult,
    isTerminalJob,
    normalizeGatewayUrl,
    parseTaskJson,
    taskKey,
    validateTask
  };
});
