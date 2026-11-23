import type { GatewayInbound, GatewayUserContent } from "./inbound-message.js";
import type { CurrentPoll } from "./polls.js";

export function combineInbound(items: Array<GatewayInbound & { currentPoll?: CurrentPoll }>):
  GatewayInbound & { currentPoll?: CurrentPoll } {
  if (!items.length) throw new Error("cannot combine an empty inbound batch");
  if (items.length === 1) return items[0];
  const blocks: Exclude<GatewayUserContent, string> = [];
  let pollIndex = -1;
  items.forEach((item, index) => { if (item.currentPoll) pollIndex = index; });
  if (pollIndex >= 0) blocks.push({ type: "text",
    text: `投票工具 imessage_vote_current_poll 对应「${items[pollIndex].currentPoll!.title}」，请使用该投票的选项编号。` });
  for (const [index, item] of items.entries()) {
    const content = typeof item.content === "string" ? [{ type: "text" as const, text: item.content }] : item.content;
    blocks.push(...content.map((block, blockIndex) => index > 0 && blockIndex === 0 && block.type === "text"
      ? { ...block, text: block.text.replace(/^<conversation_path="iMessage"(?: current_time="[^"]*")? \/>\n?/, "") }
      : block).filter(block => block.type !== "text" || block.text.length > 0));
  }
  return {
    content: blocks.every((block) => block.type === "text")
      ? blocks.map((block) => (block as { text: string }).text).join("\n") : blocks,
    sourceMessage: items[items.length - 1].sourceMessage,
    currentPoll: items[pollIndex]?.currentPoll,
  };
}
