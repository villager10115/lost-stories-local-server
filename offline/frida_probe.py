import json
import sys

import frida


SOURCE = r"""
rpc.exports.probe = function () {
  return Process.enumerateModules()
    .filter(m => m.name.toLowerCase().includes("mono"))
    .map(m => ({
      name: m.name,
      base: m.base,
      size: m.size,
      exports: Process.getModuleByName(m.name).enumerateExports()
        .map(e => e.name)
        .filter(n => n.startsWith("mono_"))
        .slice(0, 1000)
    }));
};
"""


def main():
    pid = int(sys.argv[1])
    session = frida.attach(pid)
    script = session.create_script(SOURCE)
    script.load()
    print(json.dumps(script.exports_sync.probe(), indent=2))
    session.detach()


if __name__ == "__main__":
    main()
