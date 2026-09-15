import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const BRIDGE = new URL("./sqlite_d1.py", import.meta.url);
const BRIDGE_PATH = fileURLToPath(BRIDGE);

class SqliteD1Statement {
  constructor(db, sql, params = []) {
    this.db = db;
    this.sql = sql;
    this.params = params;
  }

  bind(...params) {
    return new SqliteD1Statement(this.db, this.sql, params);
  }

  async first() {
    const response = await this.db.query(this.sql, this.params);
    return response.results?.[0] ?? null;
  }

  async all() {
    const response = await this.db.query(this.sql, this.params);
    return { results: response.results || [] };
  }

  async run() {
    return this.db.query(this.sql, this.params);
  }
}

export class SqliteD1 {
  constructor({ python = process.env.PYTHON || "python" } = {}) {
    this.child = spawn(python, ["-X", "utf8", BRIDGE_PATH], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.nextId = 1;
    this.pending = new Map();
    this.beforeBatch = null;
    this.stderr = "";
    this.closePromise = null;
    this.exitState = null;
    this.exitPromise = new Promise((resolve) => {
      this.child.once("close", (code, signal) => {
        this.exitState = { code, signal };
        resolve(this.exitState);
      });
    });
    this.reader = createInterface({ input: this.child.stdout });
    this.reader.on("line", (line) => {
      let response;
      try {
        response = JSON.parse(line);
      } catch (error) {
        this.#rejectAll(new Error(`invalid sqlite bridge response: ${line}`));
        return;
      }
      const pending = this.pending.get(response.id);
      if (!pending) return;
      this.pending.delete(response.id);
      if (response.ok) pending.resolve(response);
      else pending.reject(new Error(response.error || "sqlite bridge request failed"));
    });
    this.child.stderr.on("data", (chunk) => {
      this.stderr += String(chunk);
    });
    this.child.on("error", (error) => this.#rejectAll(error));
    this.child.on("close", (code) => {
      if (code !== 0) {
        this.#rejectAll(new Error(`sqlite bridge exited with ${code}: ${this.stderr}`));
      } else {
        this.#rejectAll(new Error("sqlite bridge closed"));
      }
    });
  }

  #rejectAll(error) {
    for (const { reject } of this.pending.values()) reject(error);
    this.pending.clear();
  }

  #request(op, payload = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.child.stdin.write(`${JSON.stringify({ id, op, ...payload })}\n`);
    });
  }

  async #waitForExit(timeoutMs) {
    if (this.exitState) return true;
    let timer;
    const exited = await Promise.race([
      this.exitPromise.then(() => true),
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(false), timeoutMs);
      }),
    ]);
    if (timer) clearTimeout(timer);
    return exited;
  }

  prepare(sql) {
    return new SqliteD1Statement(this, sql);
  }

  async query(sql, params = []) {
    return this.#request("query", { sql, params });
  }

  async batch(statements) {
    if (this.beforeBatch) await this.beforeBatch(statements);
    const response = await this.#request("batch", {
      statements: statements.map((statement) => ({
        sql: statement.sql,
        params: statement.params,
      })),
    });
    // D1Database#batch resolves to one result object per prepared statement.
    return response.results || [];
  }

  async close() {
    if (!this.child) return;
    if (this.closePromise) return this.closePromise;

    const child = this.child;
    this.closePromise = (async () => {
      if (this.exitState) return;
      let closeResult = "closed";
      if (child.exitCode === null && child.signalCode === null) {
        // Bound the request itself.  A broken bridge can stop reading stdin,
        // so waiting only after the request resolves would still hang cleanup.
        let timer;
        try {
          closeResult = await Promise.race([
            this.#request("close").then(() => "closed", () => "failed"),
            new Promise((resolve) => {
              timer = setTimeout(() => resolve("timeout"), 2000);
            }),
          ]);
        } finally {
          if (timer) clearTimeout(timer);
        }
      }
      try {
        child.stdin.end();
      } catch (_) {
        // The child may have closed stdin while handling the close request.
      }
      this.reader.close();

      // The close response is emitted before Python has actually terminated.
      // Wait for this instance's own child, then kill only that child if a
      // broken bridge ignores the request.  Keep the timeout bounded so a
      // test cleanup cannot hold the Node process open indefinitely.
      if (this.exitState) return;
      if (closeResult !== "closed") {
        child.kill();
        await this.#waitForExit(1000);
        return;
      }
      const exited = await this.#waitForExit(2000);
      if (!exited && !this.exitState) {
        child.kill();
        await this.#waitForExit(1000);
      }
    })();
    return this.closePromise;
  }
}

export async function queryRows(db, sql, ...params) {
  return (await db.prepare(sql).bind(...params).all()).results;
}
