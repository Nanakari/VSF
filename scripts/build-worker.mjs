import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(projectDir, "dist");
const serverDir = path.join(distDir, "server");
const openaiDir = path.join(distDir, ".openai");

fs.rmSync(distDir, { recursive: true, force: true });
fs.mkdirSync(serverDir, { recursive: true });
fs.mkdirSync(openaiDir, { recursive: true });

const read = (relativePath) => fs.readFileSync(path.join(projectDir, relativePath), "utf8");
let worker = read("worker/index.js");
const assets = {
  __SITE_HTML__: read("site/index.html"),
  __SITE_CSS__: read("site/styles.css"),
  __SITE_JS__: read("site/app.js"),
  __SITE_FAVICON__: read("site/favicon.svg"),
};

for (const [token, value] of Object.entries(assets)) {
  const placeholder = `"${token}"`;
  if (!worker.includes(placeholder)) throw new Error(`Missing worker placeholder: ${token}`);
  worker = worker.replace(placeholder, JSON.stringify(value));
}

fs.writeFileSync(path.join(serverDir, "index.js"), worker, "utf8");
fs.copyFileSync(path.join(projectDir, ".openai", "hosting.json"), path.join(openaiDir, "hosting.json"));
console.log(`Built ${path.join("dist", "server", "index.js")}`);
