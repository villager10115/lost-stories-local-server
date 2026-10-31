"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "interaction_hooks.js"), "utf8");
const elements = [];
function element(id, tagName, className, label) {
  const item = {
    id,
    tagName,
    className,
    innerText: label,
    textContent: label,
    complete: true,
    naturalWidth: 16,
    getAttribute: () => "",
    getBoundingClientRect: () => ({ x: 1, y: 2, width: 100, height: 30 }),
    matches: () => false
  };
  elements.push(item);
  return item;
}
const button = element("open", "BUTTON", "primary", "Open");
const document = {
  title: "Test",
  readyState: "complete",
  addEventListener() {},
  body: { innerText: "Home Open" },
  images: [element("", "IMG", "", "")],
  querySelectorAll: selector => selector.includes("button") ? [button] : [],
  getElementsByTagName: () => [button]
};
const window = { addEventListener() {} };
const context = {
  window,
  document,
  location: { hash: "#/home", origin: "http://127.0.0.1:18865", pathname: "/web/index.html", href: "http://127.0.0.1:18865/web/index.html" },
  Element: class {},
  getComputedStyle: () => ({ display: "block", visibility: "visible" }),
  addEventListener() {},
  setTimeout() {}
};
vm.runInNewContext(source, context);
const snapshot = window.__localClickAuditSnapshot();
if (snapshot.url !== "http://127.0.0.1:18865/web/index.html") throw Error("url missing");
if (snapshot.counts.buttons !== 1) throw Error("button count missing");
if (!snapshot.controls.length && !snapshot.headings.length) throw Error("UI snapshot did not parse controls");
console.log("dual client hook contract passed");
