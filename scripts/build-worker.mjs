import fs from "node:fs";
import path from "node:path";
import { bundleWorker, projectDir } from "./worker-build.mjs";

const distDir = path.join(projectDir, "dist");
const serverDir = path.join(distDir, "server");
const openaiDir = path.join(distDir, ".openai");
const drizzleSourceDir = path.join(projectDir, "drizzle");
const drizzleOutputDir = path.join(openaiDir, "drizzle");

// Bundle before replacing the previous artifact, and only clean our own
// output directory. Refuse a redirected output directory (symlink/junction).
const worker = await bundleWorker();
if (path.dirname(path.resolve(distDir)) !== projectDir
  || (fs.existsSync(distDir) && fs.lstatSync(distDir).isSymbolicLink())) {
  throw new Error("Unsafe build output directory");
}
fs.rmSync(distDir, { recursive: true, force: true });
fs.mkdirSync(serverDir, { recursive: true });
fs.mkdirSync(openaiDir, { recursive: true });
fs.cpSync(drizzleSourceDir, drizzleOutputDir, { recursive: true });

fs.writeFileSync(path.join(serverDir, "index.js"), worker, "utf8");
fs.copyFileSync(path.join(projectDir, ".openai", "hosting.json"), path.join(openaiDir, "hosting.json"));
console.log(`Built ${path.join("dist", "server", "index.js")}`);
