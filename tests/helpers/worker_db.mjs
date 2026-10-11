import fs from "node:fs";

import { SqliteD1 } from "./sqlite_d1.mjs";

// Every Worker test uses the production migrations, including their foreign
// keys and unique constraints. Do not maintain a second handwritten schema.
export async function createMigratedDb() {
  const db = new SqliteD1();
  try {
    await db.prepare("PRAGMA foreign_keys = ON").run();
    const directory = new URL("../../drizzle/", import.meta.url);
    for (const file of fs.readdirSync(directory).filter((name) => name.endsWith(".sql")).sort()) {
      const statements = fs.readFileSync(new URL(file, directory), "utf8")
        .split(/-->\s*statement-breakpoint/)
        .map((sql) => sql.trim())
        .filter(Boolean);
      for (const sql of statements) await db.prepare(sql).run();
    }
    return db;
  } catch (error) {
    await db.close();
    throw error;
  }
}
