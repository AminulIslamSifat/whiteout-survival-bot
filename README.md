# ❄️ Whiteout Survival Autopilot (WOS-Bot)

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Status](https://img.shields.io/badge/Status-Active%20Development-orange?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-blueviolet?style=flat-square)
![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen?style=flat-square)

**A high-performance, intelligent automation suite for Whiteout Survival**

Built with Python · OpenCV · PaddleOCR · FastAPI OCR Server · Real-time Screen Mirroring

[How It Works](#-the-bot-brain-how-it-works) • [Quick Start](#-quickstart-arch-linux) • [Features](#-features--use-cases) • [Structure](#-project-structure) • [Roadmap](#-roadmap)

</div>

---

> **💡 Platform Note:** High-speed streaming mode is optimized for **Linux** using `v4l2loopback`.
> Windows users fall back to standard ADB screen capture with reduced performance.

> **⚠️ Security Note:** Never commit `db/account.json` to version control. It contains sensitive credentials. Make sure it's listed in your `.gitignore`.

---

## 📋 Table of Contents

- [How It Works](#-the-bot-brain-how-it-works)
- [Resolution Requirements](#-attention-resolution-lock-)
- [Quick Start — Linux](#-quickstart-arch-linux)
- [Quick Start — Windows](#-quickstart-windows-fallback)
- [Task Scheduling](#-task-scheduling)
- [Features](#-features--use-cases)
- [Project Structure](#-project-structure)
- [Configuration](#-configuration)
- [Security](#-security)
- [Troubleshooting](#-troubleshooting)
- [Platform Support](#-linux-vs-windows-support)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [Changelog](#-changelog)
- [Disclaimer](#-disclaimer)

---

## 🧠 The Bot Brain: How It Works

The bot operates on a **Research → Strategy → Execution** loop:

1. **Vision Engine** 👁️
   Instead of simple coordinate clicking, the bot "sees" the game using a hybrid approach of **PaddleOCR** (for reading text) and **OpenCV Template Matching** (for identifying icons).

2. **Fuzzy Logic** 🎯
   Uses `rapidfuzz` to handle OCR misreads (e.g., reading `'0'` as `'O'`), ensuring actions don't fail due to tiny text variations.

3. **Local OCR Server** ⚡
   A dedicated FastAPI server handles heavy lifting for image processing, keeping the main bot logic lightweight and fast.

4. **FSM Navigation** 🗺️ *(In Development)*
   A navigation graph that calculates the shortest path between game screens (e.g., jumping from "World Map" directly to "Alliance Tech").

---

## ⚠️ ATTENTION: Resolution Lock ⚠️

> **🔴 CRITICAL:** This bot is hardcoded for **1080×2460 resolution**.

**If your device uses a different resolution:**
- ❌ ROI detection will fail
- ❌ Clicks will land in incorrect locations
- ❌ The bot may perform unintended actions

**Verify your device resolution:**
```bash
adb shell wm size
```

### 📝 Planned Solution

An **Auto-Calibration Suite** is under development. In a future release, the bot will:
- ✅ Auto-detect your device resolution on first run
- ✅ Execute a guided "World Tour" of all game screens
- ✅ Dynamically generate resolution-specific coordinates in `references/TextArea/`

**Status:** Coming soon

---

## 🚀 Quickstart (Arch Linux)

### Prerequisites

- Android device or emulator with Whiteout Survival installed
- Arch Linux system (or equivalent distro with `pacman`)
- ADB debugging enabled on your Android device
- USB cable (if using a physical device)
- Python 3.10+

### 1️⃣ Install System Dependencies

```bash
sudo pacman -Syu scrcpy v4l2loopback-dkms v4l2loopback-utils android-tools uv
```

| Package | Purpose |
| :--- | :--- |
| `scrcpy` | High-speed screen mirroring |
| `v4l2loopback` | Virtual video device driver |
| `uv` | Fast Python package manager |
| `android-tools` | ADB utilities |

### 2️⃣ Initialize V4L2 Loopback *(Recommended)*

Enable the virtual video device for high-speed OCR streaming:

```bash
sudo modprobe v4l2loopback video_nr=10 card_label="scrcpy" exclusive_caps=1
```

> **💡 Tip:** To auto-load on every boot, add the following to `/etc/modules-load.d/v4l2loopback.conf`:
> ```
> v4l2loopback
> ```
> And create `/etc/modprobe.d/v4l2loopback.conf` with:
> ```
> options v4l2loopback video_nr=10 card_label="scrcpy" exclusive_caps=1
> ```

### 3️⃣ Set Up the Python Environment

```bash
cd ~/wos
uv venv          # Create virtual environment
uv sync          # Install all dependencies from pyproject.toml
```

### 4️⃣ Start the OCR Server

Open a **dedicated terminal** and run:

```bash
cd ~/wos
uv run python -m core.ocr
```

This launches the FastAPI OCR server at `http://localhost:8000`. Keep this terminal open.

### 5️⃣ Configure Your Accounts

```bash
cp db/account.json.example db/account.json
```

Edit `db/account.json` with your actual credentials:

```json
{
  "your_email@gmail.com": {
    "priority": 1,
    "player": [
      {
        "id": "12345678",
        "name": "Your Chief Name"
      }
    ]
  }
}
```

| Field | Description |
| :--- | :--- |
| `priority` | Processing order — lower number runs first |
| `id` | Player ID found in-game via Chief Profile (top-left corner) |
| `name` | Character name used for account switching |

> **⚠️ Important:** Add `db/account.json` to your `.gitignore` immediately. See [Security](#-security).

### 6️⃣ Launch the Bot

In a **separate terminal**:

```bash
cd ~/wos
python Main/main.py
```

The bot will:
- ✅ Auto-detect your device via ADB
- ✅ Launch Whiteout Survival if not already running
- ✅ Initialize your player profile
- ✅ Open the interactive task selection menu
- ✅ Begin running selected daily tasks

---

## 🪟 Quickstart (Windows Fallback)

> **Note:** Windows support is limited. High-speed V4L2 streaming is not natively available. ADB-only mode is slower but functional.

### Prerequisites

- Python 3.10+ installed from [python.org](https://python.org)
- ADB installed — download [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)
- USB debugging enabled on your Android device

### 1️⃣ Install Python Dependencies

```powershell
pip install uv
cd wos
uv venv
uv sync
```

### 2️⃣ Add ADB to PATH

```powershell
# Add platform-tools folder to your system PATH, then verify:
adb version
```

### 3️⃣ Start OCR Server

```powershell
uv run python -m core.ocr
```

### 4️⃣ Configure Accounts & Launch

Follow the same steps as Linux — [Step 5](#5️⃣-configure-your-accounts) and [Step 6](#6️⃣-launch-the-bot) above.

> **Performance note:** Without V4L2 streaming, screen capture uses ADB screencap which is significantly slower. For best results, use Linux or WSL2.

---

## 🗂️ Task Scheduling

Task scheduling uses an **interactive selector** at startup.

When you run `python Main/main.py`, the bot opens a menu from `Main/task_menu.py`. You can select tasks by:

| Input Method | Example |
| :--- | :--- |
| Number | `1,3,6` |
| Task key | `vip,mail,heal` |
| Task title | `VIP Rewards, Mail Rewards` |

Press **Enter** (or type `all` / `default` / `*`) to run the full default task list.

### Default Task List (in order)

| # | Task |
| :--- | :--- |
| 1 | VIP Rewards |
| 2 | Exploration Idle Income |
| 3 | Continue Exploring |
| 4 | Mail Rewards |
| 5 | Life Essence |
| 6 | Train Troops |
| 7 | Arena |
| 8 | Chief Order |
| 9 | Ally Treasure |
| 10 | Pet Exploration |
| 11 | Labyrinth |
| 12 | Alliance Auto Join |
| 13 | Alliance Chests |
| 14 | Alliance Tech |
| 15 | Alliance Help |
| 16 | Alliance Triumph |
| 17 | Heal |
| 18 | World Gather |
| 19 | Missions Reward |

> **Notes:**
> - Tasks run in the exact order shown unless you provide a custom subset.
> - Invalid selections are rejected and the menu is re-shown.
> - Completion is tracked per player in `db/completion_log.txt`.
> - Players completed within the 3-hour skip window are automatically skipped.

---

## 🛠️ Features & Use Cases

### 🌍 World Operations
- **Gathering** — Intelligent resource search (Meat/Wood/Coal/Iron) with troop equalization and recall logic
- **Healing** — Auto-heal wounded troops with optimal item usage

### 🏰 Alliance Management
- **Tech Contribution** — Contribute to tech trees automatically
- **Help Members** — Provide help to alliance members in need
- **Chests** — Collect alliance chests on cooldown
- **Rallies** — Auto-join war rallies and contribute
- **Triumph Collection** — Harvest alliance triumph rewards

### ⚔️ Combat & Exploration
- **Arena Battles** — Daily automated arena fights
- **Labyrinth Runs** — Complete labyrinth dungeons
- **Intel Missions** — Auto-complete Beast hunts, Survivor rescues, Exploration intel

### 🎖️ Growth & Progression
- **Troop Training** — Auto-train Infantry, Lancers, and Marksmen
- **Pet Exploration** — Auto-start pet expeditions and claim rewards
- **Chief Order** — Activate and track chief order progression

### 💰 Rewards
- **VIP Rewards** — Collect daily VIP bonuses and auto-buy VIP time when profitable
- **Mail** — Auto-collect all mail rewards
- **Missions** — Collect mission rewards
- **Life Essence** — Harvest life essence drops
- **Events** — Collect event-specific rewards

---

## 📁 Project Structure

```
wos/
├── Main/
│   ├── main.py                 # Entry point, account loop, and task execution
│   └── task_menu.py            # Interactive task selection and task registry
├── core/
│   ├── ocr.py                  # FastAPI OCR server
│   ├── core.py                 # Vision engine (template matching, OCR)
│   ├── change_player.py        # Account/character switching
│   ├── recalibrate.py          # Auto-calibration tools
│   └── backup/                 # Legacy versions
├── cmd_program/
│   ├── screen_action.py        # ADB touch/swipe actions
│   ├── screen_stream.py        # scrcpy streaming setup
│   └── scrcpy_config.json      # Stream configuration
├── usecases/                   # Feature modules
│   ├── gather.py               # Resource gathering
│   ├── alliance.py             # Alliance tasks
│   ├── arena.py                # Arena battles
│   ├── exploration.py          # Exploration intel
│   ├── labyrinth.py            # Labyrinth runs
│   ├── pet.py                  # Pet mechanics
│   └── [other features].py
├── db/
│   ├── account.json            # ⚠️ Account/player config — NEVER commit this
│   ├── account.json.example    # Safe template — commit this
│   ├── completion_log.txt      # Daily task completion tracking
│   └── players/                # Per-player data
├── references/
│   ├── icon/                   # PNG templates for icon matching
│   │   ├── alliance/
│   │   ├── arena/
│   │   └── [other categories]/
│   └── TextArea/               # JSON ROI definitions
│       ├── Home.json
│       ├── Home.Alliance.json
│       └── [all screen definitions].json
└── test/                       # Debug & testing utilities
```

---

## ⚙️ Configuration

### account.json

The main configuration file for accounts and players. Located at `db/account.json`.

```json
{
  "email@example.com": {
    "priority": 1,
    "player": [
      {
        "id": "12345678",
        "name": "ChiefName"
      }
    ]
  },
  "second_account@example.com": {
    "priority": 2,
    "player": [
      {
        "id": "87654321",
        "name": "AnotherChief"
      }
    ]
  }
}
```

Multiple accounts are supported. Set `priority` values to control execution order.

### scrcpy_config.json

Controls the screen mirroring stream. Located at `cmd_program/scrcpy_config.json`. Adjust bitrate, resolution, and device serial here if needed.

---

## 🔐 Security

**Your `db/account.json` contains sensitive account credentials. Protect it.**

Make sure your `.gitignore` includes:

```gitignore
db/account.json
db/players/
db/completion_log.txt
```

Never share your `account.json` publicly or commit it to any repository. Use `db/account.json.example` as a safe template for sharing.

---

## 🖥️ Linux vs Windows Support

| Feature | Linux | Windows |
| :--- | :--- | :--- |
| ADB Support | ✅ | ✅ |
| Standard Screencap | ✅ | ✅ |
| **High-Speed Scrcpy Stream** | ✅ Native | ❌ Requires WSL2 + v4l2 |
| V4L2 Direct Streaming | ✅ Native | ❌ Not Available |
| Performance | 🚀 Ultra Fast | 🐢 Standard |
| Setup Complexity | ⭐ Straightforward | ⭐⭐ Extra steps needed |

**Recommended:** Linux (full native support)
**Fallback:** Windows with ADB only (slower but functional)

---

## 🛠️ Troubleshooting

### OCR Server Won't Start

**Error:** `ModuleNotFoundError` or port already in use

```bash
# Check if port 8000 is occupied
lsof -i :8000

# Kill the existing process
kill -9 <PID>

# Reinstall dependencies and retry
cd ~/wos
uv sync
uv run python -m core.ocr
```

### Bot Clicks in Wrong Locations

**Cause:** Resolution mismatch — bot is hardcoded for 1080×2460

```bash
# Verify your device resolution
adb shell wm size

# Expected output:
# Physical size: 1080x2460
```

If your resolution differs, the Auto-Calibration Suite is in development. In the meantime, manually update ROI coordinates in `references/TextArea/` (advanced).

### ADB Connection Issues

```bash
# Restart ADB daemon
adb kill-server
adb start-server

# List connected devices
adb devices

# If device shows as unauthorized, re-accept the prompt on your device
```

### V4L2 Loopback Not Detected

```bash
# Check if the module is loaded
lsmod | grep v4l2loopback

# Reinstall and reload if missing
sudo dkms remove v4l2loopback/0.12.7 --all
sudo pacman -S v4l2loopback-dkms

sudo modprobe -r v4l2loopback
sudo modprobe v4l2loopback video_nr=10 card_label="scrcpy" exclusive_caps=1
```

### PaddleOCR Installation Fails

PaddleOCR requires Python 3.10+. Verify your version:

```bash
python --version
# Should be 3.10 or higher
```

If using `uv`, ensure your venv uses the right Python:

```bash
uv venv --python 3.10
uv sync
```

---

## 🚀 Roadmap

### Phase 1 — Current
- ✅ Core daily task automation
- ✅ Multi-account support
- ✅ Interactive task selector
- ⏳ Auto-calibration suite
- ⏳ Windows setup guide

### Phase 2 — Planned
- 📋 Advanced FSM navigation (Dijkstra-based pathfinding)
- 📋 Event-specific strategies (Tundra Adventure, Sunfire Castle)
- 📋 Enhanced anti-detection (human-like click patterns)

### Phase 3 — Future
- 🔮 Multi-device simultaneous control
- 🔮 Web dashboard for monitoring
- 🔮 Community script marketplace

---

## 📦 Dependencies

**Core Requirements:**
- Python 3.10+
- OpenCV (`cv2`)
- PaddleOCR
- FastAPI & Uvicorn
- RapidFuzz
- Requests
- Rich (CLI output)

See `pyproject.toml` for the full pinned dependency list.

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create a feature branch:** `git checkout -b feature/your-feature-name`
3. **Make your changes** and test thoroughly
4. **Submit a Pull Request** with a clear description of what you changed and why

### Code Guidelines
- Follow PEP 8 style guidelines
- Add docstrings to all new functions
- Test with multiple accounts where applicable
- Document any new game screen modules in `references/TextArea/`
- Never commit `db/account.json`

---

## 📝 Changelog

### v0.2.0 — Current (Active Development)
- Added interactive task selector (`Main/task_menu.py`)
- Added per-player completion tracking with 3-hour skip window
- Added multi-account priority ordering
- Improved OCR fuzzy matching accuracy

### v0.1.0 — Initial Release
- Core daily task automation
- FastAPI OCR server
- ADB screen capture and touch actions
- Linux V4L2 high-speed streaming support
- Multi-account support

---

## 📄 License & Disclaimer

### License
This project is released under the **MIT License**. See the `LICENSE` file for details.

### ⚠️ Disclaimer

**Use this bot at your own risk.**

This project is **for educational purposes only**. Using automation tools may violate the **Terms of Service** of Whiteout Survival. The authors are **not responsible for**:
- Account suspension or bans
- In-game penalties
- Loss of progress or items
- Any violation of game terms

**Always read the game's ToS before using automation tools.**

---

## 📞 Support

- **Bugs:** Open an issue via [GitHub Issues](../../issues)
- **Ideas:** Start a thread in [GitHub Discussions](../../discussions)
- **Docs:** Check the wiki for advanced topics

---

<div align="center">

Made with ❄️ by the WOS Bot community

⭐ **Star this repo if you find it useful!**

</div>