import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import frida

from engine_compare import build_report


SOURCE = r"""
const config = __CONFIG__;
const mono = Process.getModuleByName("mono-2.0-bdwgc.dll");
const pointerSize = Process.pointerSize;

function getExport(name) {
  const address = mono.getExportByName(name);
  if (address.isNull()) throw new Error("Missing Mono export: " + name);
  return address;
}

const monoGetRootDomain = new NativeFunction(getExport("mono_get_root_domain"), "pointer", []);
const monoThreadAttach = new NativeFunction(getExport("mono_thread_attach"), "pointer", ["pointer"]);
const monoDomainAssemblyOpen = new NativeFunction(
  getExport("mono_domain_assembly_open"), "pointer", ["pointer", "pointer"]);
const monoAssemblyGetImage = new NativeFunction(
  getExport("mono_assembly_get_image"), "pointer", ["pointer"]);
const monoClassFromName = new NativeFunction(
  getExport("mono_class_from_name"), "pointer", ["pointer", "pointer", "pointer"]);
const monoClassGetMethod = new NativeFunction(
  getExport("mono_class_get_method_from_name"), "pointer", ["pointer", "pointer", "int"]);
const monoCompileMethod = new NativeFunction(
  getExport("mono_compile_method"), "pointer", ["pointer"]);
const monoObjectGetClass = new NativeFunction(
  getExport("mono_object_get_class"), "pointer", ["pointer"]);
const monoClassGetName = new NativeFunction(
  getExport("mono_class_get_name"), "pointer", ["pointer"]);
const monoClassGetNamespace = new NativeFunction(
  getExport("mono_class_get_namespace"), "pointer", ["pointer"]);
const monoClassGetField = new NativeFunction(
  getExport("mono_class_get_field_from_name"), "pointer", ["pointer", "pointer"]);
const monoFieldGetOffset = new NativeFunction(
  getExport("mono_field_get_offset"), "int", ["pointer"]);
const monoClassValueSize = new NativeFunction(
  getExport("mono_class_value_size"), "int", ["pointer", "pointer"]);
const monoRuntimeInvoke = new NativeFunction(
  getExport("mono_runtime_invoke"), "pointer",
  ["pointer", "pointer", "pointer", "pointer"]);
const monoStringToUtf8 = new NativeFunction(
  getExport("mono_string_to_utf8"), "pointer", ["pointer"]);
const monoFree = new NativeFunction(
  getExport("mono_free"), "void", ["pointer"]);
const monoJitInfoTableFind = new NativeFunction(
  getExport("mono_jit_info_table_find"), "pointer",
  ["pointer", "pointer"]);
const monoJitInfoGetMethod = new NativeFunction(
  getExport("mono_jit_info_get_method"), "pointer", ["pointer"]);
const monoMethodGetName = new NativeFunction(
  getExport("mono_method_get_name"), "pointer", ["pointer"]);
const monoMethodGetClass = new NativeFunction(
  getExport("mono_method_get_class"), "pointer", ["pointer"]);

const rootDomain = monoGetRootDomain();
monoThreadAttach(rootDomain);
const assemblyPath = Memory.allocUtf8String(config.assemblyPath);
const assembly = monoDomainAssemblyOpen(rootDomain, assemblyPath);
if (assembly.isNull()) throw new Error("Assembly did not open: " + config.assemblyPath);
const image = monoAssemblyGetImage(assembly);
if (image.isNull()) throw new Error("Assembly image missing");

function cString(value) {
  return Memory.allocUtf8String(value);
}

function stringValue(value) {
  if (value.isNull()) return "";
  const ptr = monoStringToUtf8(value);
  if (ptr.isNull()) return "";
  try {
    return ptr.readUtf8String() || "";
  } finally {
    monoFree(ptr);
  }
}

function pointerCString(value) {
  if (!value || value.isNull()) return "";
  return value.readUtf8String() || "";
}

function managedSymbol(address) {
  try {
    const jitInfo = monoJitInfoTableFind(rootDomain, address);
    if (jitInfo.isNull()) return null;
    const method = monoJitInfoGetMethod(jitInfo);
    if (method.isNull()) return null;
    const klass = monoMethodGetClass(method);
    const namespace = klass.isNull()
      ? "" : pointerCString(monoClassGetNamespace(klass));
    const className = klass.isNull()
      ? "" : pointerCString(monoClassGetName(klass));
    const methodName = pointerCString(monoMethodGetName(method));
    return [namespace, className, methodName].filter(Boolean).join(".");
  } catch (_) {
    return null;
  }
}

function getPropertyString(object, name) {
  if (object.isNull()) return "";
  const klass = monoObjectGetClass(object);
  const method = monoClassGetMethod(klass, cString(name), 0);
  if (method.isNull()) return "";
  const exception = Memory.alloc(pointerSize);
  exception.writePointer(ptr(0));
  const result = monoRuntimeInvoke(method, object, ptr(0), exception);
  if (!exception.isNull() && !exception.readPointer().isNull()) return "";
  return stringValue(result);
}

function getStructFieldString(data, className, fieldName) {
  if (data.isNull()) return "";
  const klass = classFor("", className);
  const alignment = Memory.alloc(4);
  const size = monoClassValueSize(klass, alignment);
  const range = Process.findRangeByAddress(data);
  if (!range || size <= 0 || data.add(size).compare(range.base.add(range.size)) > 0) {
    throw new Error("Struct pointer is outside a readable range");
  }
  const field = monoClassGetField(klass, cString(fieldName));
  if (field.isNull()) return "";
  const offset = monoFieldGetOffset(field);
  const value = data.add(offset).readPointer();
  return stringValue(value);
}

function getObjectFieldPointer(object, fieldName) {
  if (object.isNull()) return ptr(0);
  const klass = monoObjectGetClass(object);
  const field = monoClassGetField(klass, cString(fieldName));
  if (field.isNull()) return ptr(0);
  const offset = monoFieldGetOffset(field);
  return object.add(offset).readPointer();
}

function classFor(namespace, name, targetImage = image) {
  const klass = monoClassFromName(
    targetImage, cString(namespace), cString(name));
  if (klass.isNull()) throw new Error("Class not found: " + namespace + "." + name);
  return klass;
}

function stringCandidate(value) {
  if (!value) return null;
  try {
    if (value.isNull()) return null;
    const klass = monoObjectGetClass(value);
    if (klass.isNull()) return null;
    const name = monoClassGetName(klass);
    if (name.isNull() || name.readUtf8String() !== "String") return null;
    return stringValue(value);
  } catch (_) {
    return null;
  }
}

function methodFor(klass, name, parameterCount) {
  const method = monoClassGetMethod(klass, cString(name), parameterCount);
  if (method.isNull()) {
    throw new Error("Method not found: " + name + "/" + parameterCount);
  }
  const code = monoCompileMethod(method);
  if (code.isNull()) throw new Error("Method did not compile: " + name);
  return { method, code };
}

function emit(payload) {
  send(Object.assign({
    type: "engine_event",
    source: config.client,
    timestamp: Date.now(),
    threadId: Process.getCurrentThreadId()
  }, payload));
}

const hooks = [];
function installHook(
    label, namespace, className, methodName, parameterCount, handler,
    onLeaveHandler, targetImage = image) {
  const klass = classFor(namespace, className, targetImage);
  const target = methodFor(klass, methodName, parameterCount);
  const listener = Interceptor.attach(target.code, {
    onEnter(args) {
      this.startedMs = Date.now();
      try {
        handler.call(this, args);
      } catch (error) {
        emit({
          operation: "hook_error",
          hook: label,
          error: String(error && error.stack || error)
        });
      }
    },
    onLeave() {
      emit({
        operation: label + "_leave",
        elapsedMs: Date.now() - this.startedMs
      });
      if (onLeaveHandler) {
        try {
          onLeaveHandler.call(this);
        } catch (error) {
          emit({
            operation: "hook_error",
            hook: label,
            error: String(error && error.stack || error)
          });
        }
      }
    }
  });
  hooks.push({
    label,
    method: target.method,
    code: target.code,
    listener
  });
}

installHook(
  "command",
  "Zero.Web.Command",
  "CommandManager",
  "SendCommand",
  2,
  function (args) {
    const messageData = args[2];
    emit({
      operation: "command",
      path: getStructFieldString(messageData, "UniWebViewMessage", "Path"),
      rawMessage: getStructFieldString(messageData, "UniWebViewMessage", "RawMessage"),
      scheme: getStructFieldString(messageData, "UniWebViewMessage", "Scheme")
    });
  }
);

installHook(
  "callback",
  "Zero.Web",
  "VuplexWebView",
  "KickCallback",
  2,
  function (args) {
    let stack = [];
    try {
      stack = Thread.backtrace(this.context, Backtracer.ACCURATE)
        .slice(0, 16)
        .map(function (address) {
          const managed = managedSymbol(address);
          return managed || DebugSymbol.fromAddress(address).toString();
        });
    } catch (error) {
      stack = ["backtrace unavailable: " + String(error)];
    }
    emit({
      operation: "callback",
      callbackName: stringValue(args[2]),
      message: stringValue(args[1]),
      stack
    });
  }
);

installHook(
  "not_found_execute",
  "Zero.Web.Command",
  "NotFound",
  "Execute",
  1,
  function (args) {
    const commandName = getObjectFieldPointer(args[0], "_commandName");
    emit({
      operation: "not_found_command",
      commandName: stringValue(commandName)
    });
  }
);

installHook(
  "message_constructor",
  "",
  "UniWebViewMessage",
  ".ctor",
  1,
  function (args) {
    const first = args[0];
    const second = args[1];
    const firstString = stringCandidate(first);
    const rawMessage = firstString !== null
      ? firstString
      : stringCandidate(second);
    emit({
      operation: "command_message",
      rawMessage,
      argumentPointers: [first, second]
        .map(value => {
          try { return value ? value.toString() : null; } catch (_) { return null; }
        })
    });
  }
);

installHook(
  "request",
  "Zero.Network",
  "WebRequestUtils",
  "SendAsync",
  1,
  function (args) {
    const request = args[0];
    emit({
      operation: "request",
      url: getPropertyString(request, "get_url"),
      method: getPropertyString(request, "get_method")
    });
  }
);

installHook(
  "live2d_contains_group",
  "GameEngine.Live2d.Command",
  "Live2dCommandController",
  "ContainsGroupId",
  1,
  function (args) {
    const controller = args[0];
    const dictionary = getObjectFieldPointer(
      controller, "_commandQueueDictionary");
    emit({
      operation: "live2d_contains_group",
      controller: controller.toString(),
      groupId: stringValue(args[1]),
      commandQueueDictionary: dictionary.toString()
    });
  }
);

installHook(
  "live2d_preload_start",
  "GameEngine.Live2d.Command",
  "Live2dCommandController",
  "Preload",
  2,
  function (args) {
    const controller = args[0];
    let callbackType = "";
    try {
      const callbackClass = monoObjectGetClass(args[2]);
      if (!callbackClass.isNull()) callbackType = monoClassGetName(callbackClass).readUtf8String();
    } catch (_) {}
    emit({
      operation: "live2d_preload_start",
      controller: controller.toString(),
      commandQueueDictionary: getObjectFieldPointer(
        controller, "_commandQueueDictionary").toString(),
      callbackType
    });
  }
);

installHook(
  "live2d_release",
  "GameEngine.Live2d.Command",
  "Live2dCommandController",
  "Release",
  0,
  function (args) {
    const controller = args[0];
    emit({
      operation: "live2d_release",
      controller: controller.toString(),
      commandQueueDictionary: getObjectFieldPointer(
        controller, "_commandQueueDictionary").toString()
    });
  }
);

installHook(
  "live2d_destroy",
  "GameEngine.Live2d.Command",
  "Live2dCommandController",
  "Destroy",
  0,
  function (args) {
    const controller = args[0];
    emit({
      operation: "live2d_destroy",
      controller: controller.toString(),
      commandQueueDictionary: getObjectFieldPointer(
        controller, "_commandQueueDictionary").toString()
    });
  }
);

rpc.exports.status = function () {
  return {
    client: config.client,
    pid: Process.id,
    rootDomain: rootDomain.toString(),
    assemblyPath: config.assemblyPath,
    hooks: hooks.map(function (item) {
      return {
        label: item.label,
        method: item.method.toString(),
        code: item.code.toString()
      };
    })
  };
};

emit({ operation: "trace_ready", hooks: hooks.length });
"""


TARGETS = {
    "official": (
        int(os.environ.get("OFFICIAL_PID", "5240")),
        r"D:\LostStories_OfficialCompare_20261020\Client\ロススト_Data\Managed\Assembly-CSharp.dll",
    ),
    "packaged-local": (
        int(os.environ.get("LOCAL_PID", "29820")),
        r"D:\LostStories_Private_Client_20261019\Client\ロススト_Data\Managed\Assembly-CSharp.dll",
    ),
}


def clean_text(value, limit=8000):
    text = str(value or "")
    for marker in ("access_token=", "onetime_token=", "token=", "authorization="):
        while marker in text.lower():
            start = text.lower().find(marker)
            end = start + len(marker)
            while end < len(text) and text[end] not in "&,; \r\n\"'":
                end += 1
            text = text[:start + len(marker)] + "[redacted]" + text[end:]
    return text[:limit]


def sanitize(value):
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            lowered = key.lower()
            if any(word in lowered for word in ("token", "cookie", "authorization", "password")):
                result[key] = "[redacted]"
            else:
                result[key] = sanitize(child)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return clean_text(value)
    return value


class EventWriter:
    def __init__(self, root):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.count = 0

    def write(self, event):
        event = sanitize(event)
        event["receivedAt"] = datetime.now(timezone.utc).isoformat()
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        source = event.get("source", "common")
        directory_name = (
            "official" if source == "official"
            else "local" if source == "packaged-local"
            else "common"
        )
        with self.lock:
            with (self.root / "engine-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            client_directory = self.root / directory_name
            client_directory.mkdir(parents=True, exist_ok=True)
            with (client_directory / "engine-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            self.count += 1


def attach_client(client, pid, assembly_path, writer):
    session = frida.attach(pid)
    config = {
        "client": client,
        "assemblyPath": assembly_path,
    }
    source = SOURCE.replace("__CONFIG__", json.dumps(config))
    script = session.create_script(source)

    def on_message(message, data):
        if message.get("type") == "error":
            writer.write({
                "source": client,
                "pid": pid,
                "operation": "frida_error",
                "error": message.get("description"),
                "stack": message.get("stack"),
            })
            return
        payload = message.get("payload")
        if isinstance(payload, dict):
            payload.setdefault("source", client)
            payload.setdefault("pid", pid)
            writer.write(payload)

    script.on("message", on_message)
    script.load()
    status = script.exports_sync.status()
    return session, script, status


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python engine_trace.py OUTPUT_DIRECTORY")
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / "engine-status.json"
    writer = EventWriter(output)
    (output / "engine-trace.pid").write_text(str(os.getpid()), encoding="ascii")

    attached = {}
    errors = {}
    for client, (pid, assembly_path) in TARGETS.items():
        try:
            session, script, status = attach_client(client, pid, assembly_path, writer)
            attached[client] = (session, script, status)
            writer.write({
                "source": client,
                "pid": pid,
                "operation": "attached",
                "hooks": status.get("hooks"),
            })
        except Exception as error:
            errors[client] = str(error)
            writer.write({
                "source": client,
                "pid": pid,
                "operation": "attach_error",
                "error": str(error),
            })

    try:
        while attached:
            status = {
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "eventCount": writer.count,
                "attached": {name: value[2] for name, value in attached.items()},
                "errors": errors,
            }
            status_path.write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                build_report(output)
            except Exception as error:
                writer.write({
                    "operation": "comparison_error",
                    "error": str(error),
                })
            time.sleep(1)
    finally:
        for session, _script, _status in attached.values():
            try:
                session.detach()
            except Exception:
                pass
        (output / "engine-trace.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
