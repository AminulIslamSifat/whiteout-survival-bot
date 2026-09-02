"""
Interactive FSM test — run with device connected and OCR server running.

Usage: uv run python test_fsm.py
"""
import sys
sys.path.insert(0, ".")

from config import load_config
from device.adb import DeviceContext, list_adb_devices
from vision.ocr_client import OCRClient
from vision.calibration import load_calibration
from vision.interaction import Interaction
from navigation.fsm import GameFSM
from usecases._compat import set_active_interaction

# Setup
cfg = load_config()
devices = list_adb_devices()
if not devices:
    print("❌ No ADB devices found")
    sys.exit(1)

device = DeviceContext(devices[0])
ocr = OCRClient(cfg)
cal = load_calibration(cfg, device_id=devices[0])
ix = Interaction(device, ocr, cal, cfg)
fsm = GameFSM(ix)
set_active_interaction(ix)

print(f"📱 Device: {devices[0]} ({device.screen_width}x{device.screen_height})")
print(f"🔗 OCR: {cfg.ocr_base_url}")
print(f"   Healthy: {ocr.is_healthy()}")
print()

# Test 1: Detect current state
print("═══ Test 1: State Detection ═══")
state = fsm.detect_state()
print(f"Detected state: {state}")
print()

# Test 2: Show graph connectivity
print("═══ Test 2: Graph Connectivity ═══")
for src, neighbors in sorted(fsm.graph.items()):
    targets = list(neighbors.keys())
    print(f"  {src:20s} → {', '.join(targets)}")
print()

# Test 3: Pathfinding (dry run, no taps)
print("═══ Test 3: Pathfinding (dry run) ═══")
test_paths = [
    ("main_city", "arena"),
    ("main_city", "alliance_tech"),
    ("world", "intel"),
    ("alliance", "main_city"),
    ("main_city", "heal"),
]
for src, dst in test_paths:
    path = fsm.find_path(src, dst)
    if path:
        print(f"  ✅ {src} → {dst}: {' → '.join(path)}")
    else:
        print(f"  ❌ {src} → {dst}: NO PATH")
print()

# Test 4: Navigate to main_city (actually taps)
print("═══ Test 4: Navigate to main_city ═══")
result = fsm.go_home()
print(f"go_home() returned: {result}")
print(f"Current state after: {fsm.current_state}")
print()

# Test 5: Navigate to alliance and back
print("═══ Test 5: Navigate to alliance → main_city ═══")
result = fsm.navigate_to("alliance")
print(f"navigate_to('alliance') returned: {result}")
print(f"Current state: {fsm.current_state}")

if result:
    result = fsm.navigate_to("main_city")
    print(f"navigate_to('main_city') returned: {result}")
    print(f"Current state: {fsm.current_state}")

print()
print("Done! If all tests passed, FSM is working correctly.")
