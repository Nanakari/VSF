import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const testsDir = path.join(projectDir, "tests");
const testFile = /^(?:test[-_].*|.*\.test|.*_test)\.(?:cjs|js|mjs)$/;

function collectTests(directory) {
  const files = [];
  if (!fs.existsSync(directory)) return files;
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...collectTests(fullPath));
    else if (entry.isFile() && testFile.test(entry.name)) files.push(fullPath);
  }
  return files;
}

const testFiles = collectTests(testsDir).sort();
if (testFiles.length === 0) {
  console.error("No Worker behavior tests found.");
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...testFiles], {
  cwd: projectDir,
  stdio: "inherit",
  windowsHide: true,
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
