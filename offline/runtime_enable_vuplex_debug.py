import json
import sys

import frida


SOURCE = r"""
const config = __CONFIG__;
const mono = Process.getModuleByName("mono-2.0-bdwgc.dll");
const pointerSize = Process.pointerSize;

function exportAddress(name) {
  const address = mono.getExportByName(name);
  if (address.isNull()) throw new Error("Missing Mono export: " + name);
  return address;
}

const getRootDomain = new NativeFunction(
  exportAddress("mono_get_root_domain"), "pointer", []);
const threadAttach = new NativeFunction(
  exportAddress("mono_thread_attach"), "pointer", ["pointer"]);
const domainAssemblyOpen = new NativeFunction(
  exportAddress("mono_domain_assembly_open"), "pointer", ["pointer", "pointer"]);
const assemblyGetImage = new NativeFunction(
  exportAddress("mono_assembly_get_image"), "pointer", ["pointer"]);
const classFromName = new NativeFunction(
  exportAddress("mono_class_from_name"), "pointer",
  ["pointer", "pointer", "pointer"]);
const getMethod = new NativeFunction(
  exportAddress("mono_class_get_method_from_name"), "pointer",
  ["pointer", "pointer", "int"]);
const runtimeInvoke = new NativeFunction(
  exportAddress("mono_runtime_invoke"), "pointer",
  ["pointer", "pointer", "pointer", "pointer"]);
const objectToString = new NativeFunction(
  exportAddress("mono_object_to_string"), "pointer",
  ["pointer", "pointer"]);
const stringToUtf8 = new NativeFunction(
  exportAddress("mono_string_to_utf8"), "pointer", ["pointer"]);
const monoFree = new NativeFunction(
  exportAddress("mono_free"), "void", ["pointer"]);

const rootDomain = getRootDomain();
threadAttach(rootDomain);
const assemblyPath = Memory.allocUtf8String(config.assemblyPath);
const assembly = domainAssemblyOpen(rootDomain, assemblyPath);
if (assembly.isNull()) throw new Error("Assembly did not open");
const image = assemblyGetImage(assembly);
if (image.isNull()) throw new Error("Assembly image missing");
const klass = classFromName(
  image, Memory.allocUtf8String("Vuplex.WebView"),
  Memory.allocUtf8String("StandaloneWebView"));
if (klass.isNull()) throw new Error("StandaloneWebView class missing");
const method = getMethod(
  klass, Memory.allocUtf8String("EnableRemoteDebugging"), 1);
if (method.isNull()) throw new Error("EnableRemoteDebugging method missing");
const value = Memory.alloc(4);
value.writeS32(config.port);
const parameters = Memory.alloc(pointerSize);
parameters.writePointer(value);
const exception = Memory.alloc(pointerSize);
exception.writePointer(ptr(0));
const result = runtimeInvoke(method, ptr(0), parameters, exception);
const pending = exception.readPointer();
let exceptionText = null;
if (!pending.isNull()) {
  const exceptionObject = Memory.alloc(pointerSize);
  exceptionObject.writePointer(ptr(0));
  const rendered = objectToString(pending, exceptionObject);
  if (!rendered.isNull()) {
    const utf8 = stringToUtf8(rendered);
    if (!utf8.isNull()) {
      exceptionText = utf8.readUtf8String();
      monoFree(utf8);
    }
  }
}
rpc.exports.result = function () {
  return {
    invoked: true,
    port: config.port,
    result: result.toString(),
    exception: pending.isNull() ? null : pending.toString(),
    exceptionText
  };
};
"""


def main():
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: python runtime_enable_vuplex_debug.py PID ASSEMBLY_PATH PORT")
    pid = int(sys.argv[1])
    assembly_path = sys.argv[2]
    port = int(sys.argv[3])
    session = frida.attach(pid)
    source = SOURCE.replace(
        "__CONFIG__",
        json.dumps({"assemblyPath": assembly_path, "port": port}),
    )
    script = session.create_script(source)
    script.load()
    print(json.dumps(script.exports_sync.result(), indent=2))
    session.detach()


if __name__ == "__main__":
    main()
