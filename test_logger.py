import os
import shutil
import sys
import tempfile
import types

tmp_root = tempfile.mkdtemp(prefix="loggertest_")
os.makedirs(os.path.join(tmp_root, "lib"), exist_ok=True)
os.makedirs(os.path.join(tmp_root, "logs"), exist_ok=True)

shutil.copy("/home/claude/work/logger.py", os.path.join(tmp_root, "lib", "logger.py"))


config_stub = types.ModuleType("config")
config_stub.GRAYLOG_HOST = ""
config_stub.GRAYLOG_PORT = 0
config_stub.MACHINE_TOKEN = "tok"
config_stub.UNIQUE_ID = "uid"
sys.modules["config"] = config_stub


sys.path.insert(0, tmp_root)
lib_pkg = types.ModuleType("lib")
lib_pkg.__path__ = [os.path.join(tmp_root, "lib")]
sys.modules["lib"] = lib_pkg

import importlib.util
spec = importlib.util.spec_from_file_location(
    "lib.logger", os.path.join(tmp_root, "lib", "logger.py")
)
logger_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logger_mod)


loggers = [logger_mod.get_logger(f"Test{i}") for i in range(100)]

also = [logger_mod.Logger(f"OldStyle{i}") for i in range(100)]

import logging
root = logging.getLogger("veskald_bridge")
file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
stream_handlers = [
    h for h in root.handlers
    if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
]

print(f"Root handlers: {len(root.handlers)}")
print(f"  FileHandlers: {len(file_handlers)}")
print(f"  StreamHandlers: {len(stream_handlers)}")

assert len(file_handlers) == 1, f"Expected exactly 1 FileHandler, got {len(file_handlers)}"
assert len(stream_handlers) == 1, f"Expected exactly 1 StreamHandler, got {len(stream_handlers)}"


for lg in loggers + also:
    own = [h for h in lg.handlers]
    assert len(own) == 0, f"{lg.name} has {len(own)} own handlers"


test_msg = "UNIQUE_TEST_MARKER_42"
loggers[0].info(test_msg, extra={"foo": "bar"})


for h in root.handlers:
    h.flush()


log_file = os.path.join(tmp_root, "logs", "veskald_bridge.log")
with open(log_file, "r") as f:
    content = f.read()

count = content.count(test_msg)
print(f"\nMessage occurrences in log file: {count}")
assert count == 1, f"Expected 1 occurrence, got {count} (duplicate handlers leaking)"


test_msg2 = "OLD_INTERFACE_MARKER_99"
also[0].info(test_msg2)
for h in root.handlers:
    h.flush()
with open(log_file, "r") as f:
    content = f.read()
count2 = content.count(test_msg2)
assert count2 == 1, f"Expected 1 occurrence via old interface, got {count2}"

print("\n✅ All logger tests passed.")
print("  - Exactly 1 FileHandler regardless of how many loggers created")
print("  - Exactly 1 StreamHandler")
print("  - No duplicate writes to the log file")
print("  - Old `Logger(name)` interface backward-compatible")

# Уборка
shutil.rmtree(tmp_root)