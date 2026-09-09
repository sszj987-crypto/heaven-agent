// Isolated, in-memory API for desktop UI checks. Never proxies to real services.
// Run: node tests/fixtures/desktop-api.mjs
import { createServer } from "node:http";

const settings = {
  llm: { base_url: "https://dialogue.example.test", model: "dialogue-demo", temperature: 0.7, api_key_configured: true },
  tts: { provider: "minimax", minimax: { base_url: "https://speech.example.test", model: "speech-demo", api_key_configured: true } },
  log_level: "error",
};
const calls = [];
let history = Array.from({ length: 24 }, (_, index) => ({
  role: index % 2 ? "assistant" : "user",
  content: index % 2
    ? `演示回复 ${index}：这些是用于检查布局的虚构文字。${"把值得记住的小事慢慢整理下来。".repeat(10)}`
    : `演示问题 ${index}：我们聊一聊今天的事情吧。`,
}));

const server = createServer(async (request, response) => {
  response.setHeader("Access-Control-Allow-Origin", "http://localhost:3337");
  response.setHeader("Access-Control-Allow-Headers", "Content-Type");
  response.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
  const json = (body, status = 200) => {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(body));
  };
  if (request.method === "OPTIONS") return json({});
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  let body = {};
  try {
    if (chunks.length) body = JSON.parse(Buffer.concat(chunks).toString());
  } catch {
    return json({ message: "测试请求必须是 JSON" }, 400);
  }
  const route = `${request.method} ${request.url}`;
  if (route === "GET /settings") return json(settings);
  if (route === "GET /__checks") return json({ settings, calls });
  if (route === "PUT /settings") {
    calls.push({ route, sections: Object.keys(body), llmKeySent: Object.hasOwn(body.llm ?? {}, "api_key"), ttsKeySent: Object.hasOwn(body.tts?.minimax ?? {}, "api_key") });
    if (body.llm) {
      const { api_key, ...fields } = body.llm;
      Object.assign(settings.llm, fields, api_key !== undefined ? { api_key_configured: Boolean(api_key) } : {});
    }
    if (body.tts) {
      settings.tts.provider = body.tts.provider;
      const { api_key, ...fields } = body.tts.minimax;
      Object.assign(settings.tts.minimax, fields, api_key !== undefined ? { api_key_configured: Boolean(api_key) } : {});
    }
    if (body.log_level) settings.log_level = body.log_level;
    return json({ status: "ok" });
  }
  if (route === "POST /settings/test-llm") return json({ connected: true });
  if (route === "POST /settings/test-tts") return json({ code: "test_unavailable", message: "语音服务暂时不可用，请稍后重试", retryable: true, request_id: "fixture-tts" }, 503);
  if (route === "GET /chat/history") return json({ messages: history });
  if (route === "DELETE /chat/history") {
    history = [];
    return json({ status: "ok" });
  }
  if (route === "POST /chat") {
    calls.push({ route });
    return json({
      response_text: `这是一条演示回复。${"记忆里的每一件小事，都可以慢慢说。".repeat(8)} https://example.test/${"very-long-path-".repeat(40)}`,
      has_voice: true,
      instruct_text: "",
      used_memories: [{ id: "fixture-memory-1", content: "演示资料：喜欢在傍晚散步。", dimension: "basic_info", source_type: "manual" }],
      safety_state: "normal",
    });
  }
  if (route === "POST /chat/audio") {
    calls.push({ route });
    return json({ code: "test_audio_failed", message: "演示语音准备失败，请重试", retryable: true, request_id: "fixture-audio" }, 503);
  }
  return json({ message: "未定义的测试接口" }, 404);
});

server.listen(8437, "127.0.0.1", () => console.log("Desktop fixture API ready on 127.0.0.1:8437"));
process.on("SIGTERM", () => server.close());
process.on("SIGINT", () => server.close());
