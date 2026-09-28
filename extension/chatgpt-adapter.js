(function attachChatGPTAdapter(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.AgentBridgeChatGPT = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildAdapter() {
  "use strict";

  const ASSISTANT_SELECTOR = '[data-message-author-role="assistant"]';
  const COMPOSER_SELECTORS = [
    "#prompt-textarea",
    'textarea[data-id="root"]',
    'textarea[placeholder*="Message"]',
    'div[contenteditable="true"][data-virtualkeyboard="true"]',
    'div[contenteditable="true"]'
  ];
  const SEND_SELECTORS = [
    'button[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label*="Send"]'
  ];
  const STOP_SELECTORS = [
    'button[data-testid="stop-button"]',
    'button[aria-label="Stop generating"]',
    'button[aria-label*="Stop"]'
  ];

  function queryFirst(documentRef, selectors) {
    for (const selector of selectors) {
      const element = documentRef.querySelector(selector);
      if (element) return element;
    }
    return null;
  }

  function assistantMessages(documentRef) {
    return Array.from(documentRef.querySelectorAll(ASSISTANT_SELECTOR));
  }

  function taskCandidates(message) {
    const candidates = [];
    const languageBlocks = message.querySelectorAll('code[class*="language-agentbridge-task"]');
    for (const block of languageBlocks) {
      if (block.textContent) candidates.push({ rawJson: block.textContent });
    }
    for (const block of message.querySelectorAll("pre code")) {
      if (block.textContent) candidates.push({ rawJson: block.textContent });
    }
    if (message.textContent) candidates.push({ fencedText: message.textContent });
    return candidates;
  }

  function composer(documentRef) {
    return queryFirst(documentRef, COMPOSER_SELECTORS);
  }

  function sendButton(documentRef) {
    return queryFirst(documentRef, SEND_SELECTORS);
  }

  function isGenerating(documentRef) {
    return Boolean(queryFirst(documentRef, STOP_SELECTORS));
  }

  function setComposerText(element, text, documentRef) {
    element.focus();
    if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
      const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value").set;
      setter.call(element, text);
    } else {
      element.replaceChildren();
      const selection = documentRef.getSelection();
      const range = documentRef.createRange();
      range.selectNodeContents(element);
      selection.removeAllRanges();
      selection.addRange(range);
      if (!documentRef.execCommand("insertText", false, text)) {
        element.textContent = text;
      }
    }
    element.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      composed: true,
      inputType: "insertText",
      data: text
    }));
  }

  function wait(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
  }

  async function waitUntilIdle(documentRef, timeoutMilliseconds = 30000) {
    const deadline = Date.now() + timeoutMilliseconds;
    let stableSince = null;
    while (Date.now() < deadline) {
      if (!isGenerating(documentRef)) {
        if (stableSince === null) stableSince = Date.now();
        if (Date.now() - stableSince >= 800) return;
      } else {
        stableSince = null;
      }
      await wait(200);
    }
    throw new Error("ChatGPT did not become idle before timeout");
  }

  async function insertAndMaybeSend(documentRef, text, autoSend) {
    await waitUntilIdle(documentRef);
    const input = composer(documentRef);
    if (!input) throw new Error("ChatGPT composer was not found");
    setComposerText(input, text, documentRef);
    if (!autoSend) return;
    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      const button = sendButton(documentRef);
      if (button && !button.disabled) {
        button.click();
        return;
      }
      await wait(100);
    }
    throw new Error("ChatGPT send button did not become available");
  }

  return {
    ASSISTANT_SELECTOR,
    COMPOSER_SELECTORS,
    SEND_SELECTORS,
    assistantMessages,
    composer,
    insertAndMaybeSend,
    isGenerating,
    sendButton,
    taskCandidates,
    waitUntilIdle
  };
});
