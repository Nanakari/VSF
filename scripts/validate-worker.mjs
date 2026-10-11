import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { bundleWorker, projectDir } from "./worker-build.mjs";

const workerPath = path.join(projectDir, "dist", "server", "index.js");
const clientPath = path.join(projectDir, "site", "app.js");
const hostingPath = path.join(projectDir, "dist", ".openai", "hosting.json");
if (!fs.existsSync(workerPath)) throw new Error("dist/server/index.js is missing; run npm run build first");
if (!fs.existsSync(hostingPath)) throw new Error("dist/.openai/hosting.json is missing; run npm run build first");
const hosting = JSON.parse(fs.readFileSync(hostingPath, "utf8"));
if (hosting.d1 !== "DB") throw new Error("hosting.json must contain the logical D1 binding DB");
function assertSameTree(sourcePath, outputPath) {
  if (!fs.existsSync(outputPath)) throw new Error(`Missing generated file: ${outputPath}`);
  if (fs.statSync(sourcePath).isDirectory()) {
    const names = fs.readdirSync(sourcePath).sort();
    if (JSON.stringify(names) !== JSON.stringify(fs.readdirSync(outputPath).sort())) {
      throw new Error(`Generated directory is stale: ${outputPath}`);
    }
    for (const name of names) assertSameTree(path.join(sourcePath, name), path.join(outputPath, name));
  } else if (!fs.readFileSync(sourcePath).equals(fs.readFileSync(outputPath))) {
    throw new Error(`Generated file is stale: ${outputPath}`);
  }
}
assertSameTree(path.join(projectDir, ".openai", "hosting.json"), hostingPath);
assertSameTree(path.join(projectDir, "drizzle"), path.join(projectDir, "dist", ".openai", "drizzle"));
const source = fs.readFileSync(workerPath, "utf8");
if (/__SITE_(HTML|CSS|JS|FAVICON)__/.test(source)) throw new Error("Worker assets were not embedded");
if (source !== await bundleWorker()) throw new Error("Worker bundle is stale; run npm run build");
execFileSync(process.execPath, ["--check", workerPath], { stdio: "inherit", windowsHide: true });
execFileSync(process.execPath, ["--check", clientPath], { stdio: "inherit", windowsHide: true });
const { default: worker } = await import(pathToFileURL(workerPath).href);
if (typeof worker?.fetch !== "function") throw new Error("Worker fetch export is missing");
for (const [route, file] of [["/", "index.html"], ["/styles.css", "styles.css"], ["/app.js", "app.js"], ["/favicon.svg", "favicon.svg"]]) {
  const response = await worker.fetch(new Request(`https://validation.test${route}`), {});
  if (response.status !== 200 || await response.text() !== fs.readFileSync(path.join(projectDir, "site", file), "utf8")) {
    throw new Error(`Bundled asset does not match site/${file}`);
  }
}
console.log("Worker bundle validation passed.");
