// Minimal DOM/event surface for testing requests and UI state without a browser
// dependency. It deliberately does not implement layout or rendering.
import vm from "node:vm";

export class Element {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.events = new Map();
    this.dataset = {};
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.open = false;
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  addEventListener(name, callback) {
    const callbacks = this.events.get(name) || [];
    callbacks.push(callback);
    this.events.set(name, callbacks);
  }
  async dispatch(name) {
    await Promise.all((this.events.get(name) || []).map((callback) => callback({ preventDefault() {} })));
  }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; }
  find(className) {
    if ((this.className || "").split(" ").includes(className)) return this;
    for (const child of this.children) {
      const result = child.find(className);
      if (result) return result;
    }
    return null;
  }
}

export async function settle() {
  for (let i = 0; i < 4; i += 1) await new Promise(setImmediate);
}

export function runBrowserScript(source, { search = "", fetch, nodes = new Map(), globals = {} } = {}) {
  const location = { pathname: "/", search, reload() { location.reloads += 1; }, reloads: 0 };
  const window = new Element();
  window.location = location;
  window.history = Object.fromEntries(["pushState", "replaceState"].map((name) => [name, (_state, _title, url) => {
    location.search = new URL(url, "https://site.test").search;
  }]));
  const timers = [];
  window.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length; };
  window.clearInterval = () => {};
  window.setInterval = window.setTimeout;
  window.scrollTo = () => {};
  const document = {
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, new Element());
      return nodes.get(selector);
    },
    querySelectorAll(selector) { return nodes.get(selector) || []; },
    createElement: (tag) => new Element(tag),
  };
  vm.runInNewContext(source, {
    window, document, fetch, URLSearchParams, Intl, AbortController,
    console: { error() {}, warn() {} },
    ...globals,
  });
  return { nodes, window, document, timers };
}
