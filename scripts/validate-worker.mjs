import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const workerPath = path.join(projectDir, "dist", "server", "index.js");
const hostingPath = path.join(projectDir, "dist", ".openai", "hosting.json");
if (!fs.existsSync(workerPath)) throw new Error("dist/server/index.js is missing; run npm run build first");
if (!fs.existsSync(hostingPath)) throw new Error("dist/.openai/hosting.json is missing; run npm run build first");
const hosting = JSON.parse(fs.readFileSync(hostingPath, "utf8"));
if (hosting.d1 !== "DB") throw new Error("hosting.json must contain the logical D1 binding DB");
const source = fs.readFileSync(workerPath, "utf8");
if (!source.includes("export default")) throw new Error("Worker default export is missing");
if (source.includes("__SITE_HTML__")) throw new Error("Worker HTML asset was not embedded");
execFileSync(process.execPath, ["--check", workerPath], { stdio: "inherit" });
console.log("Worker bundle validation passed.");
