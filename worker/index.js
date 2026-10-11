// HTTP routing and static assets only; business rules live in the services.
import { json, textResponse } from "./http.js";
import { queryOverview, searchEntries, searchGroups } from "./search.js";
import { commitPatch, commitSnapshot, patch, seed, startPatch, startSnapshot } from "./sync.js";

const pageHtml = "__SITE_HTML__";
const stylesCss = "__SITE_CSS__";
const clientJs = "__SITE_JS__";
const faviconSvg = "__SITE_FAVICON__";

async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (request.method === "GET" && (path === "/" || path === "/index.html")) {
    return textResponse(pageHtml, "text/html; charset=utf-8");
  }
  if (request.method === "GET" && path === "/styles.css") {
    return textResponse(stylesCss, "text/css; charset=utf-8", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/app.js") {
    return textResponse(clientJs, "text/javascript; charset=utf-8", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/favicon.svg") {
    return textResponse(faviconSvg, "image/svg+xml", "public, max-age=3600");
  }
  if (request.method === "GET" && path === "/api/overview") {
    try {
      return json(await queryOverview(env));
    } catch (error) {
      console.error("overview failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "GET" && path === "/api/search") {
    try {
      return json(await searchGroups(env, url));
    } catch (error) {
      console.error("search failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "GET" && path === "/api/entries") {
    try {
      const result = await searchEntries(env, url);
      return json(result, result.ok === false ? 400 : 200);
    } catch (error) {
      console.error("entries failed", error);
      return json({ ok: false, message: "数据库暂时不可用，请稍后再试。" }, 503);
    }
  }
  if (request.method === "POST" && path === "/api/admin/snapshot/start") {
    return startSnapshot(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/patch/start") {
    return startPatch(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/patch") {
    return patch(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/patch/commit") {
    return commitPatch(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/snapshot/commit") {
    return commitSnapshot(request, env);
  }
  if (request.method === "POST" && path === "/api/admin/seed") {
    return seed(request, env);
  }
  return json({ ok: false, message: "Not found" }, 404);
}

export default {
  async fetch(request, env) {
    return handle(request, env);
  },
};
