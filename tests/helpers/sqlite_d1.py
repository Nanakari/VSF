from __future__ import annotations

import json
import sqlite3
import sys


def send(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def rows_for(cursor: sqlite3.Cursor) -> list[dict[str, object]]:
    if cursor.description is None:
        return []
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def main() -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = None
    for line in sys.stdin:
        request: object = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise RuntimeError("sqlite bridge request must be an object")
            operation = request.get("op")
            if operation == "close":
                send({"id": request.get("id"), "ok": True})
                break
            if operation == "query":
                cursor = conn.execute(request["sql"], request.get("params", []))
                send({
                    "id": request.get("id"),
                    "ok": True,
                    "results": rows_for(cursor),
                    "changes": conn.execute("SELECT changes()").fetchone()[0],
                })
                continue
            if operation == "batch":
                conn.execute("BEGIN IMMEDIATE")
                results: list[dict[str, object]] = []
                try:
                    for statement in request.get("statements", []):
                        cursor = conn.execute(statement["sql"], statement.get("params", []))
                        results.append({
                            "results": rows_for(cursor),
                            "meta": {"changes": conn.execute("SELECT changes()").fetchone()[0]},
                        })
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                send({"id": request.get("id"), "ok": True, "results": results})
                continue
            raise RuntimeError(f"unknown sqlite bridge operation: {operation!r}")
        except Exception as error:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            send({"id": request.get("id") if isinstance(request, dict) else None, "ok": False, "error": str(error)})


if __name__ == "__main__":
    main()
