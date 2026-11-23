import assert from "node:assert/strict";
import test from "node:test";
import type { Message } from "@spectrum-ts/core";
import { combineInbound } from "./inbound-batch.js";

const first = { id: "first" } as Message;
const last = { id: "last" } as Message;

test("text batches preserve ordering, boundaries and the latest reply target", () => {
  const batch = combineInbound([{ content: "one", sourceMessage: first }, { content: "two", sourceMessage: last }]);
  assert.equal(batch.content, "one\ntwo");
  assert.equal(batch.sourceMessage, last);
  const single = { content: "one", sourceMessage: first };
  assert.equal(combineInbound([single]), single);
});

test("mixed image and text batches retain all content and the latest votable poll", () => {
  const poll = { title: "Dinner?", options: ["Rice", "Noodles"], async vote() {} };
  const image = { type: "image_url" as const, image_url: { url: "data:image/png;base64,abc" } };
  const batch = combineInbound([
    { content: "poll choices", sourceMessage: first, currentPoll: poll },
    { content: [image], sourceMessage: first },
    { content: "Choose rice", sourceMessage: last },
  ]);
  assert.deepEqual(batch.content, [
    { type: "text", text: "投票工具 imessage_vote_current_poll 对应「Dinner?」，请使用该投票的选项编号。" },
    { type: "text", text: "poll choices" }, image,
    { type: "text", text: "Choose rice" },
  ]);
  assert.equal(batch.currentPoll, poll);
  assert.equal(batch.sourceMessage, last);
});

test("multiple polls identify the voting tool target by title without message numbers", () => {
  const poll = { title: "First poll", options: ["A", "B"], async vote() {} };
  const latest = { ...poll, title: "Second poll" };
  const batch = combineInbound([
    { content: "First poll", sourceMessage: first, currentPoll: poll },
    { content: "Second poll", sourceMessage: last, currentPoll: latest },
    { content: "Choose A", sourceMessage: last },
  ]);
  assert.equal(batch.currentPoll, latest);
  assert.match(String(batch.content), /对应「Second poll」/);
});

test("only the first message carries a time and path, including mixed image batches", () => {
  const prefix = '<conversation_path="iMessage" current_time="2026-10-31 12:00:00 星期六" />';
  const later = '<conversation_path="iMessage" current_time="2026-10-31 12:00:10 星期六" />';
  const image = { type: "image_url" as const, image_url: { url: "data:image/png;base64,abc" } };
  const batch = combineInbound([
    {content: prefix + '\none', sourceMessage: first},
    {content: later + '\ntwo', sourceMessage: last},
    {content: [{type: 'text', text: later}, image, {type: 'text', text: '这张图'}], sourceMessage: last},
  ]);
  assert.deepEqual(batch.content, [{type: 'text', text: prefix + '\none'}, {type: 'text', text: 'two'}, image, {type:'text', text:'这张图'}]);
  assert.equal(combineInbound([
    {content:'<conversation_path="iMessage" />\none',sourceMessage:first},
    {content:'<conversation_path="iMessage" />\ntwo',sourceMessage:last},
  ]).content, '<conversation_path="iMessage" />\none\ntwo');
});
