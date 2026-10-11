import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export function exportContract(kind) {
  return JSON.parse(execFileSync(
    process.env.PYTHON || "python",
    ["-X", "utf8", fileURLToPath(new URL("./export_contract.py", import.meta.url)), kind],
    { encoding: "utf8", windowsHide: true },
  ));
}
