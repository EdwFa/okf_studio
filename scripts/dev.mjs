// Start the server (port 8100) and the web interface (port 3100) together.
import { spawn } from "node:child_process";

const children = [
  spawn("npm", ["run", "dev", "--workspace", "server"], { stdio: "inherit" }),
  spawn("npm", ["run", "dev", "--workspace", "web"], { stdio: "inherit" }),
];
const stop = () => children.forEach((child) => child.kill("SIGTERM"));
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
children.forEach((child) => child.on("exit", (code) => { stop(); process.exitCode = code ?? 0; }));
