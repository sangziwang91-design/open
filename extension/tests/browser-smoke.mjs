import assert from "node:assert/strict";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium } from "playwright";

const TOKEN = "t".repeat(48);
const root = mkdtempSync(join(tmpdir(), "agentbridge-browser-smoke-"));
const extensionSource = resolve("extension");
const extensionPath = join(root, "extension");
const userDataDir = join(root, "profile");
const executablePath = process.env.AGENTBRIDGE_CHROMIUM_EXECUTABLE || undefined;
let receivedTask = null;

cpSync(extensionSource, extensionPath, {
  recursive: true,
  filter(source) {
    return !source.endsWith("README.md") && !source.includes(`${join("extension", "tests")}`);
  }
});
const manifestPath = join(extensionPath, "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
manifest.content_scripts[0].matches.push("http://127.0.0.1/*");
manifest.web_accessible_resources[0].matches.push("http://127.0.0.1/*");
writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));

function sendJson(response, status, body, origin = "*") {
  const content = Buffer.from(JSON.stringify(body));
  response.writeHead(status, {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Content-Type": "application/json",
    "Content-Length": content.length
  });
  response.end(content);
}

const fixture = `<!doctype html>
<html><body>
  <main id="messages"></main>
  <div id="prompt-textarea" contenteditable="true" data-virtualkeyboard="true"></div>
  <button type="button" data-testid="send-button">Send</button>
  <script>
    window.sentMessages = [];
    window.loopComplete = null;
    const composer = document.getElementById("prompt-textarea");
    document.querySelector('[data-testid="send-button"]').addEventListener("click", () => {
      const text = composer.innerText || composer.textContent || "";
      window.sentMessages.push(text);
      composer.replaceChildren();
      if (text.includes("会话 ID：") && !window.taskEmitted) {
        window.taskEmitted = true;
        const session = text.match(/会话 ID：(\\S+)/)[1];
        const task = {
          protocol: "agentbridge/1",
          message_type: "task",
          session_id: session,
          request_id: "REQ-BROWSER-SMOKE",
          title: "Browser smoke",
          goal: "Exercise the browser-to-gateway loop",
          constraints: ["bounded fixture"],
          acceptance: [{id: "A1", type: "command", command: "python --version", expected_exit_code: 0}],
          timeout_seconds: 30
        };
        const message = document.createElement("article");
        message.setAttribute("data-message-author-role", "assistant");
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.className = "language-agentbridge-task";
        code.textContent = JSON.stringify(task);
        pre.appendChild(code);
        message.appendChild(pre);
        document.getElementById("messages").appendChild(message);
      } else if (text.includes("agentbridge-result")) {
        window.loopComplete = text;
      }
    });
  </script>
</body></html>`;

const server = createServer((request, response) => {
  const origin = request.headers.origin || "*";
  if (request.method === "OPTIONS") {
    response.writeHead(204, {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Headers": "Authorization, Content-Type",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Private-Network": "true"
    });
    response.end();
    return;
  }
  if (request.url === "/fixture") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(fixture);
    return;
  }
  if (request.headers.authorization !== `Bearer ${TOKEN}`) {
    sendJson(response, 401, { error: "unauthorized" }, origin);
    return;
  }
  if (request.method === "GET" && request.url === "/health") {
    sendJson(response, 200, { status: "READY", protocol: "agentbridge/1" }, origin);
    return;
  }
  if (request.method === "POST" && request.url === "/v1/jobs") {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      receivedTask = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const result = {
        protocol: "agentbridge/1",
        message_type: "result",
        session_id: receivedTask.session_id,
        request_id: receivedTask.request_id,
        job_id: "JOB-BROWSERSMOKE",
        task_id: "TASK-BROWSERSMOKE",
        run_id: "RUN-BROWSERSMOKE",
        status: "COMPLETED",
        state: "COMPLETED",
        summary: "Controlled browser fixture passed.",
        checks: [{ check_id: "A1", status: "PASS", detail: "fixture" }],
        artifacts: [],
        executor_excerpt: "fixture",
        claim_level: "EXECUTED",
        next_action: "CLOSE",
        requires_human_decision: false,
        question_to_human: null,
        error: null
      };
      sendJson(response, 201, {
        job_id: result.job_id,
        session_id: result.session_id,
        request_id: result.request_id,
        status: "FINISHED",
        task_id: result.task_id,
        run_id: result.run_id,
        result,
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      }, origin);
    });
    return;
  }
  sendJson(response, 404, { error: "not_found" }, origin);
});

await new Promise((resolvePromise) => server.listen(0, "127.0.0.1", resolvePromise));
const port = server.address().port;
let context;
try {
  context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    executablePath,
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`
    ]
  });
  let [worker] = context.serviceWorkers();
  if (!worker) worker = await context.waitForEvent("serviceworker");
  const extensionId = new URL(worker.url()).host;
  const options = await context.newPage();
  await options.goto(`chrome-extension://${extensionId}/options.html`);
  await options.evaluate(async ({ gatewayUrl, token }) => {
    await chrome.storage.sync.set({
      gatewayUrl,
      autoSend: true,
      maxSteps: 3,
      pollMilliseconds: 250,
      jobTimeoutSeconds: 30
    });
    await chrome.storage.local.set({ token });
  }, { gatewayUrl: `http://127.0.0.1:${port}`, token: TOKEN });
  await options.close();

  const page = await context.newPage();
  await page.goto(`http://127.0.0.1:${port}/fixture`);
  const connect = page.locator('#agentbridge-controls button[data-action="arm"]');
  await connect.waitFor();
  await connect.click();
  await page.waitForFunction(() => Boolean(window.loopComplete), null, { timeout: 15000 });

  const browserResult = await page.evaluate(() => ({
    sentMessages: window.sentMessages,
    loopComplete: window.loopComplete,
    status: document.getElementById("agentbridge-status").textContent
  }));
  assert.equal(receivedTask.protocol, "agentbridge/1");
  assert.equal(receivedTask.request_id, "REQ-BROWSER-SMOKE");
  assert.equal("workspace" in receivedTask, false);
  assert.match(browserResult.loopComplete, /```agentbridge-result/);
  assert.match(browserResult.loopComplete, /"status": "COMPLETED"/);
  assert.match(browserResult.status, /1\/3/);
  assert.equal(browserResult.sentMessages.length, 2);
  process.stdout.write(JSON.stringify({ status: "PASS", extensionId, steps: 1 }) + "\n");
} finally {
  if (context) await context.close();
  await new Promise((resolvePromise) => server.close(resolvePromise));
  rmSync(root, { recursive: true, force: true });
}
