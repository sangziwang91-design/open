"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const Adapter = require("../chatgpt-adapter.js");

test("uses ChatGPT author-role messages rather than scanning user messages", () => {
  let selector;
  const expected = [{ id: 1 }, { id: 2 }];
  const documentRef = {
    querySelectorAll(value) {
      selector = value;
      return expected;
    }
  };
  assert.deepEqual(Adapter.assistantMessages(documentRef), expected);
  assert.equal(selector, '[data-message-author-role="assistant"]');
});

test("prefers known ChatGPT composer and send selectors", () => {
  const hits = new Map([
    ["#prompt-textarea", { id: "composer" }],
    ['button[data-testid="send-button"]', { id: "send" }]
  ]);
  const documentRef = { querySelector: (selector) => hits.get(selector) || null };
  assert.equal(Adapter.composer(documentRef).id, "composer");
  assert.equal(Adapter.sendButton(documentRef).id, "send");
});

test("extracts rendered language blocks and fenced text fallbacks", () => {
  const language = { textContent: '{"message_type":"task"}' };
  const generic = { textContent: "generic JSON" };
  const message = {
    textContent: "```agentbridge-task\n{}\n```",
    querySelectorAll(selector) {
      if (selector.includes("language-agentbridge-task")) return [language];
      if (selector === "pre code") return [language, generic];
      return [];
    }
  };
  const values = Adapter.taskCandidates(message);
  assert.equal(values.filter((value) => value.rawJson).length, 3);
  assert.equal(values.filter((value) => value.fencedText).length, 1);
});
