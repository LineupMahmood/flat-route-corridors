Starting Container
[2026-03-12 05:19:32 +0000] [1] [INFO] Control socket listening at /app/gunicorn.ctl
[2026-03-12 05:19:32 +0000] [3] [INFO] Booting worker with pid: 3
[2026-03-12 05:19:32 +0000] [3] [ERROR] Exception in worker process
    self.callable = self.load()
Traceback (most recent call last):
                    ~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/arbiter.py", line 708, in spawn_worker
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/wsgiapp.py", line 57, in load
    worker.init_process()
    return self.load_wsgiapp()
    ~~~~~~~~~~~~~~~~~~~^^
    ~~~~~~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/workers/base.py", line 136, in init_process
[2026-03-12 05:19:32 +0000] [1] [INFO] Starting gunicorn 25.1.0
    self.load_wsgi()
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/workers/base.py", line 148, in load_wsgi
[2026-03-12 05:19:32 +0000] [1] [INFO] Listening at: http://0.0.0.0:8080 (1)
    self.wsgi = self.app.wsgi()
[2026-03-12 05:19:32 +0000] [1] [INFO] Using worker: sync
                ~~~~~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/base.py", line 66, in wsgi
  File "<frozen importlib._bootstrap_external>", line 1157, in get_code
    return util.import_app(self.app_uri)
  File "<frozen importlib._bootstrap_external>", line 1087, in source_to_code
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/util.py", line 377, in import_app
           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/app.py", line 275
    if not has_backtrack(path):
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
    mod = importlib.import_module(module)
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "/mise/installs/python/3.13.12/lib/python3.13/importlib/__init__.py", line 88, in import_module
           ~~~~~~~~~~~~~~~~~^^
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
    return _bootstrap._gcd_import(name[level:], package, level)
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/wsgiapp.py", line 47, in load_wsgiapp
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 1019, in exec_module
                               ^
IndentationError: unindent does not match any outer indentation level
unindent does not match any outer indentation level (app.py, line 275)
[2026-03-12 05:19:32 +0000] [3] [INFO] Worker exiting (pid: 3)
[2026-03-12 05:19:32 +0000] [1] [ERROR] Worker (pid:3) exited with code 3.
[2026-03-12 05:19:32 +0000] [1] [ERROR] Shutting down: Master
[2026-03-12 05:19:32 +0000] [1] [ERROR] Reason: Worker failed to boot.
[2026-03-12 05:19:33 +0000] [1] [INFO] Starting gunicorn 25.1.0
[2026-03-12 05:19:33 +0000] [1] [INFO] Listening at: http://0.0.0.0:8080 (1)
[2026-03-12 05:19:33 +0000] [1] [INFO] Using worker: sync
[2026-03-12 05:19:33 +0000] [1] [INFO] Control socket listening at /app/gunicorn.ctl
[2026-03-12 05:19:33 +0000] [3] [INFO] Booting worker with pid: 3
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/arbiter.py", line 708, in spawn_worker
    worker.init_process()
    ~~~~~~~~~~~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/workers/base.py", line 136, in init_process
    self.load_wsgi()
    ~~~~~~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/workers/base.py", line 148, in load_wsgi
    self.wsgi = self.app.wsgi()
                ~~~~~~~~~~~~~^^
[2026-03-12 05:19:33 +0000] [3] [ERROR] Exception in worker process
Traceback (most recent call last):
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/base.py", line 66, in wsgi
    self.callable = self.load()
                    ~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/wsgiapp.py", line 57, in load
    return self.load_wsgiapp()
           ~~~~~~~~~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/wsgiapp.py", line 47, in load_wsgiapp
    return util.import_app(self.app_uri)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/util.py", line 377, in import_app
unindent does not match any outer indentation level (app.py, line 275)
[2026-03-12 05:19:33 +0000] [3] [INFO] Worker exiting (pid: 3)
    mod = importlib.import_module(module)
  File "/mise/installs/python/3.13.12/lib/python3.13/importlib/__init__.py", line 88, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 1019, in exec_module
  File "<frozen importlib._bootstrap_external>", line 1157, in get_code
  File "<frozen importlib._bootstrap_external>", line 1087, in source_to_code
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "/app/app.py", line 275
    if not has_backtrack(path):
                               ^
IndentationError: unindent does not match any outer indentation level
[2026-03-12 05:19:33 +0000] [1] [ERROR] Worker (pid:3) exited with code 3.
[2026-03-12 05:19:33 +0000] [1] [ERROR] Shutting down: Master
[2026-03-12 05:19:33 +0000] [1] [ERROR] Reason: Worker failed to boot.
[2026-03-12 05:19:34 +0000] [1] [INFO] Starting gunicorn 25.1.0
[2026-03-12 05:19:34 +0000] [1] [INFO] Listening at: http://0.0.0.0:8080 (1)
[2026-03-12 05:19:34 +0000] [1] [INFO] Using worker: sync
[2026-03-12 05:19:34 +0000] [1] [INFO] Control socket listening at /app/gunicorn.ctl
[2026-03-12 05:19:34 +0000] [3] [INFO] Booting worker with pid: 3
                    ~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/wsgiapp.py", line 57, in load
[2026-03-12 05:19:34 +0000] [3] [ERROR] Exception in worker process
    return self.load_wsgiapp()
Traceback (most recent call last):
           ~~~~~~~~~~~~~~~~~^^
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/arbiter.py", line 708, in spawn_worker
    worker.init_process()
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/app/wsgiapp.py", line 47, in load_wsgiapp
    ~~~~~~~~~~~~~~~~~~~^^
    return util.import_app(self.app_uri)
  File "/app/.venv/lib/python3.13/site-packages/gunicorn/workers/base.py", line 136, in init_process
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
    self.load_wsgi()
