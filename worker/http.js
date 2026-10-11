const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

export function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: JSON_HEADERS,
  });
}

export function textResponse(value, contentType, cacheControl = "no-store") {
  return new Response(value, {
    headers: {
      "content-type": contentType,
      "cache-control": cacheControl,
    },
  });
}

export function requestText(value, maxLength = 120) {
  return String(value ?? "").trim().slice(0, maxLength);
}
