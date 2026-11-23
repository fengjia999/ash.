export type ConnectionConfig = {
  enabled: boolean; projectId: string; projectSecret: string; homeUser: string;
  allowedUsers: string[]; gatewayUrl: string; gatewaySecret: string;
};

export function validateConnection(value: unknown): ConnectionConfig {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid connection");
  const data = value as Record<string, unknown>;
  const keys = ["enabled", "projectId", "projectSecret", "homeUser", "allowedUsers", "gatewayUrl", "gatewaySecret"];
  if (Object.keys(data).some(key => !keys.includes(key)) || typeof data.enabled !== "boolean") throw new Error("invalid connection");
  for (const key of keys.filter(key => !["enabled", "allowedUsers"].includes(key))) {
    if (typeof data[key] !== "string" || (data[key] as string).length > 2000 || /[\u0000-\u001f\u007f]/u.test(data[key] as string)) throw new Error("invalid connection");
  }
  if (!Array.isArray(data.allowedUsers) || data.allowedUsers.length > 50
    || data.allowedUsers.some(v => typeof v !== "string" || !v.trim() || v.length > 200 || /[\u0000-\u001f\u007f]/u.test(v))) throw new Error("invalid connection");
  const result = Object.fromEntries(keys.map(key => [key, typeof data[key] === "string" ? data[key].trim() : data[key]])) as ConnectionConfig;
  result.allowedUsers = [...new Set(result.allowedUsers.map(value => value.trim().toLowerCase()))];
  if (result.gatewayUrl) {
    const url = new URL(result.gatewayUrl);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("invalid gateway URL");
    result.gatewayUrl = result.gatewayUrl.replace(/\/+$/, "");
  }
  if (result.enabled && (!result.projectId || !result.projectSecret || !result.homeUser || !result.allowedUsers.length || !result.gatewayUrl || !result.gatewaySecret)) throw new Error("incomplete connection");
  return result;
}
