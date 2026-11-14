import { buildApp } from "./app.ts";
import { DATA_DIR, LUKA_AGENT_DIR, PORT, WEB_PORT } from "./config.ts";

const { app } = await buildApp({
  dataDir: DATA_DIR,
  lukaAgentDir: LUKA_AGENT_DIR,
  origins: [`http://localhost:${WEB_PORT}`, `http://127.0.0.1:${WEB_PORT}`],
});
// Local only: the studio has no sign-in yet.
await app.listen({ port: PORT, host: "127.0.0.1" });
console.log(`OKF Studio server: http://127.0.0.1:${PORT}  data: ${DATA_DIR}`);
