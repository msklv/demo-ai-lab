// Проверка MCP-обёртки firecrawl-mcp изнутри кластера (копируется в под через stdin):
//   kubectl --context demo-ai-lab -n fc exec deploy/firecrawl-mcp -- node -e "$(cat scripts/fc_mcp_probe.js)"
// Ждёт: 6 инструментов, scrape example.com и скриншот (image/png). Кода возврата нет — смотреть вывод.
const U = process.env.MCP_URL || "http://127.0.0.1:8080/mcp";
const call = async (payload) => {
  const r = await fetch(U, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18" },
    body: JSON.stringify(payload),
  });
  const t = await r.text();
  const line = t.split("\n").find((l) => l.startsWith("data: "));
  return line ? JSON.parse(line.slice(6)) : JSON.parse(t);
};
const tool = (id, name, args) => call({ jsonrpc: "2.0", id, method: "tools/call", params: { name, arguments: args } });

(async () => {
  const init = await call({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "fc-probe", version: "1" } } });
  console.log("server:", JSON.stringify(init.result.serverInfo));
  const tools = (await call({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} })).result.tools.map((t) => t.name);
  console.log("tools:", tools.join(", "));
  const s = await tool(3, "firecrawl_scrape", { url: "https://example.com" });
  console.log("scrape:", (s.result.content[0].text || "").split("\n").slice(0, 3).join(" | ").slice(0, 120));
  const sh = await tool(4, "firecrawl_screenshot", { url: "https://example.com" });
  const img = (sh.result.content || []).find((c) => c.type === "image");
  console.log("screenshot:", img ? "image/png base64 " + img.data.length + " симв." : "FAIL " + JSON.stringify(sh.result).slice(0, 120));
})();
