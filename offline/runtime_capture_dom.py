import json
import sys
from pathlib import Path

import frida


SOURCE = r"""
const config = __CONFIG__;
const mono = Process.getModuleByName("mono-2.0-bdwgc.dll");
const pointerSize = Process.pointerSize;

function getExport(name) {
  const address = mono.getExportByName(name);
  if (address.isNull()) throw new Error("Missing Mono export: " + name);
  return address;
}

const getRootDomain = new NativeFunction(
  getExport("mono_get_root_domain"), "pointer", []);
const threadAttach = new NativeFunction(
  getExport("mono_thread_attach"), "pointer", ["pointer"]);
const domainAssemblyOpen = new NativeFunction(
  getExport("mono_domain_assembly_open"), "pointer", ["pointer", "pointer"]);
const assemblyGetImage = new NativeFunction(
  getExport("mono_assembly_get_image"), "pointer", ["pointer"]);
const classFromName = new NativeFunction(
  getExport("mono_class_from_name"), "pointer",
  ["pointer", "pointer", "pointer"]);
const classGetMethod = new NativeFunction(
  getExport("mono_class_get_method_from_name"), "pointer",
  ["pointer", "pointer", "int"]);
const compileMethod = new NativeFunction(
  getExport("mono_compile_method"), "pointer", ["pointer"]);
const className = new NativeFunction(
  getExport("mono_class_get_name"), "pointer", ["pointer"]);
const stringNew = new NativeFunction(
  getExport("mono_string_new"), "pointer", ["pointer", "pointer"]);
const runtimeInvoke = new NativeFunction(
  getExport("mono_runtime_invoke"), "pointer",
  ["pointer", "pointer", "pointer", "pointer"]);
const getCorlib = new NativeFunction(
  getExport("mono_get_corlib"), "pointer", []);

const rootDomain = getRootDomain();
threadAttach(rootDomain);
const assembly = domainAssemblyOpen(
  rootDomain, Memory.allocUtf8String(config.assemblyPath));
if (assembly.isNull()) throw new Error("Assembly did not open");
const image = assemblyGetImage(assembly);
if (image.isNull()) throw new Error("Assembly image missing");
const klass = classFromName(
  image, Memory.allocUtf8String("Zero.Web"),
  Memory.allocUtf8String("VuplexWebView"));
if (klass.isNull()) throw new Error("VuplexWebView class missing");
const evaluateMethod = classGetMethod(
  klass, Memory.allocUtf8String("EvaluateJS"), 1);
if (evaluateMethod.isNull()) throw new Error("EvaluateJS method missing");
const evaluateCode = compileMethod(evaluateMethod);
if (evaluateCode.isNull()) throw new Error("EvaluateJS did not compile");

const found = null;
const scanned = 0;
let webScene = null;
let findMode = null;
if (found === null) {
  const unityAssembly = domainAssemblyOpen(
    rootDomain, Memory.allocUtf8String(config.unityAssemblyPath));
  if (!unityAssembly.isNull()) {
    const unityImage = assemblyGetImage(unityAssembly);
    const unityObjectClass = classFromName(
      unityImage, Memory.allocUtf8String("UnityEngine"),
      Memory.allocUtf8String("Object"));
    const findMethod = classGetMethod(
      unityObjectClass, Memory.allocUtf8String("FindObjectOfType"), 1);
    if (!findMethod.isNull()) {
      const corlibImage = getCorlib();
      const systemTypeClass = classFromName(
        corlibImage, Memory.allocUtf8String("System"),
        Memory.allocUtf8String("Type"));
      const systemGetType = classGetMethod(
        systemTypeClass, Memory.allocUtf8String("GetType"), 1);
      const typeName = stringNew(
        rootDomain,
        Memory.allocUtf8String("Zero.Web.WebScene, Assembly-CSharp"));
      const getTypeParameters = Memory.alloc(pointerSize);
      getTypeParameters.writePointer(typeName);
      const getTypeException = Memory.alloc(pointerSize);
      getTypeException.writePointer(ptr(0));
      const runtimeType = runtimeInvoke(
        systemGetType, ptr(0), getTypeParameters, getTypeException);
      const typeParameters = Memory.alloc(pointerSize);
      typeParameters.writePointer(runtimeType);
      const findException = Memory.alloc(pointerSize);
      findException.writePointer(ptr(0));
      webScene = runtimeInvoke(
        findMethod, ptr(0), typeParameters, findException);
      if (!webScene.isNull()) findMode = "FindObjectOfType";
    }
  }
}

const snapshotSource = `
    setTimeout(function () {
      try {
        var visible = function (el) {
          var r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0;
        };
        var values = function (selector, limit) {
          return Array.from(document.querySelectorAll(selector))
            .filter(visible).slice(0, limit)
            .map(function (el) {
              return String(el.innerText || el.getAttribute("aria-label") ||
                el.title || el.id || "").replace(/\\s+/g, " ").trim();
            }).filter(Boolean);
        };
        var data = {
          href: location.href,
          hash: location.hash,
          title: document.title,
          headings: values("h1,h2,h3,[role=heading]", 30),
          buttons: values("button,[role=button],.commonBtn,.purpleBtn,.grayBtn", 80),
          dialogs: values("[role=dialog],.popupInner,[id*=Popup]", 20),
          text: String(document.body && document.body.innerText || "")
            .replace(/\\s+/g, " ").trim().slice(0, 5000)
        };
        window.vuplex.postMessage({
          type: "message",
          message: "zero://AUDIT_STATE?commandParam=" +
            encodeURIComponent(JSON.stringify(data))
        });
      } catch (_) {}
    }, 50);
  `;

let exceptionPointer = ptr(0);
if (found !== null) {
  findMode = "gc-walk";
  const managedSource = stringNew(
    rootDomain, Memory.allocUtf8String(snapshotSource));
  const parameters = Memory.alloc(pointerSize);
  parameters.writePointer(managedSource);
  const exception = Memory.alloc(pointerSize);
  exception.writePointer(ptr(0));
  runtimeInvoke(evaluateMethod, found, parameters, exception);
  exceptionPointer = exception.readPointer();
} else if (webScene !== null) {
  const kickMethod = classGetMethod(
    klass, Memory.allocUtf8String("KickCallback"), 2);
  if (kickMethod.isNull()) throw new Error("WebScene.KickCallback missing");
  const messageLiteral = stringNew(
    rootDomain,
    Memory.allocUtf8String(JSON.stringify(snapshotSource)));
  const callbackName = stringNew(
    rootDomain, Memory.allocUtf8String("eval"));
  const parameters = Memory.alloc(pointerSize * 2);
  parameters.writePointer(messageLiteral);
  parameters.add(pointerSize).writePointer(callbackName);
  const exception = Memory.alloc(pointerSize);
  exception.writePointer(ptr(0));
  runtimeInvoke(kickMethod, webScene, parameters, exception);
  exceptionPointer = exception.readPointer();
}

if (found === null && webScene === null) {
  rpc.exports.result = function () {
    return { found: false, scanned };
  };
} else {
  rpc.exports.result = function () {
    return {
      found: true,
      scanned,
      mode: findMode,
      object: (found || webScene).toString(),
      evaluateCode: evaluateCode.toString(),
      exception: (
        exceptionPointer && !exceptionPointer.isNull()
          ? exceptionPointer.toString()
          : null
      )
    };
  };
}
"""


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python runtime_capture_dom.py PID ASSEMBLY_PATH")
    pid = int(sys.argv[1])
    assembly_path = sys.argv[2]
    session = frida.attach(pid)
    unity_assembly_path = str(
        (Path(assembly_path).parent / "UnityEngine.CoreModule.dll").resolve())
    script = session.create_script(
        SOURCE.replace("__CONFIG__", json.dumps({
            "assemblyPath": assembly_path,
            "unityAssemblyPath": unity_assembly_path,
        })))
    script.load()
    print(json.dumps(script.exports_sync.result(), indent=2))
    session.detach()


if __name__ == "__main__":
    main()
