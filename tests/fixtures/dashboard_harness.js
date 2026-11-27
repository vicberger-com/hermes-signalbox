// Test harness for dashboard/dist/index.js (H5 WP3). Runs the real file under Node with stand-ins for the
// Hermes plugin SDK and React, renders the Modules view from a scenario read on stdin, and prints what a
// test needs as JSON. No dependencies; no network.
"use strict";
const fs = require("fs");
const vm = require("vm");

const scenario = JSON.parse(fs.readFileSync(0, "utf8"));
const queue = (scenario.state || []).slice(); // values the first useState calls return, in call order
const setCalls = []; // [index, value] for every state setter call
const fetches = []; // [url, options] for every request the page makes
let stateIndex = 0;

const React = {
  createElement(type, props) {
    const children = Array.prototype.slice.call(arguments, 2);
    return { type, props: props || {}, children };
  },
  useState(initial) {
    const index = stateIndex++;
    const value = queue.length ? queue.shift() : initial;
    return [value, (next) => { setCalls.push([index, next]); }];
  },
  useEffect() {},
};
const registered = {};
const SDK = {
  React,
  fetchJSON(url, options) {
    fetches.push([url, options || null]);
    const failure = (scenario.failures || {})[url];
    return failure ? Promise.reject(new Error(failure)) : Promise.resolve((scenario.replies || {})[url] || {});
  },
};
const window = {
  __HERMES_PLUGIN_SDK__: SDK,
  __HERMES_PLUGINS__: { register(name, component) { registered[name] = component; } },
};
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), { window, encodeURIComponent, JSON, String, Promise });
const view = window.__SIGNALBOX_VIEW__;

function resolve(node) {
  if (node === null || node === undefined || node === false) return null;
  if (Array.isArray(node)) return node.map(resolve).filter((n) => n !== null);
  if (typeof node !== "object") return String(node);
  if (typeof node.type === "function") return resolve(node.type(Object.assign({}, node.props, { children: node.children })));
  const props = {};
  Object.keys(node.props).forEach((key) => {
    const value = node.props[key];
    props[key] = typeof value === "function" ? "[function]" : value;
  });
  const children = [];
  node.children.forEach((child) => {
    const out = resolve(child);
    if (Array.isArray(out)) out.forEach((c) => children.push(c)); else if (out !== null) children.push(out);
  });
  return { type: node.type, props, children };
}

function find(node, test, out) {
  if (!node || typeof node !== "object") return out;
  if (Array.isArray(node)) { node.forEach((n) => find(n, test, out)); return out; }
  if (typeof node.type === "function") {
    return find(node.type(Object.assign({}, node.props, { children: node.children })), test, out);
  }
  if (test(node)) out.push(node);
  node.children.forEach((child) => find(child, test, out));
  return out;
}

async function main() {
  const out = { registered: Object.keys(registered), safe: {}, hosts: {}, models: [], clicks: [] };
  (scenario.urls || []).forEach((u) => { out.safe[u] = view.safeUrl(u); out.hosts[u] = view.hostOf(u); });
  (scenario.rows || []).forEach((row) => { out.models.push(view.rowModel(row, scenario.labels || {})); });
  const tree = view.Modules({ tick: 0, refresh() { out.refreshed = (out.refreshed || 0) + 1; } });
  out.tree = resolve(tree);
  for (const click of scenario.clicks || []) {
    const before = [fetches.length, setCalls.length];
    const hits = find(tree, (n) => n.props && n.props["data-sy"] === click.target, []);
    if (!hits.length) { out.clicks.push({ target: click.target, missing: true }); continue; }
    const handler = hits[0].props[click.event || "onClick"];
    if (typeof handler === "function") handler(click.arg === undefined ? {} : click.arg);
    await new Promise((done) => setTimeout(done, 5)); // let the request's promise settle
    out.clicks.push({
      target: click.target,
      fetches: fetches.slice(before[0]),
      sets: setCalls.slice(before[1]),
    });
  }
  process.stdout.write(JSON.stringify(out));
}

main().catch((error) => { process.stderr.write(String(error && error.stack || error)); process.exit(1); });
