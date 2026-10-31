"""Cooperative shutdown adapters for the two existing local servers."""
from pathlib import Path
import sys
import threading
import time

stop_file = Path(sys.argv[1])
kind = sys.argv[2]
arguments = sys.argv[3:]


def watch(callback):
    def poll():
        while not stop_file.exists():
            time.sleep(.2)
        callback()
    threading.Thread(target=poll, daemon=True).start()


if kind == 'state':
    import uvicorn
    original = uvicorn.Server.run
    def run(server, *args, **kwargs):
        watch(lambda: setattr(server, 'should_exit', True))
        return original(server, *args, **kwargs)
    uvicorn.Server.run = run
    sys.argv = ['cgls.app'] + arguments
    # Keep request models in their registered module so deferred annotations
    # resolve correctly during FastAPI/Pydantic request-body validation.
    from cgls.app import main
    main()
elif kind == 'page':
    import server
    original = server.LocalServer.serve_forever
    def serve(instance, *args, **kwargs):
        watch(instance.shutdown)
        return original(instance, *args, **kwargs)
    server.LocalServer.serve_forever = serve
    sys.argv = ['server.py'] + arguments
    server.main()
else:
    raise ValueError('Unknown local service')
