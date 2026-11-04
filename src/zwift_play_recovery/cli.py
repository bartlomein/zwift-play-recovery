"""Plain terminal wizard with no firmware writes before explicit confirmation."""
import argparse
import asyncio
import json
from pathlib import Path
import platform
import re
import shlex
import sys

from . import __version__
from .constants import RecoveryError, DFU, ZAP_V2
from . import devices
from .firmware import load
from .recovery import Session, recover, confirmation_text


def clean(value):
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", str(value))[:200]


def seconds(value):
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Scan duration must be a whole number of seconds.") from None
    if not 1 <= result <= 120:
        raise argparse.ArgumentTypeError("Choose a scan duration from 1 to 120 seconds.")
    return result


def demo_devices():
    return [devices.Controller("DEMO-LEFT", "Zwift Play", -49, (ZAP_V2,), bytes.fromhex("0fa101"), "Normal", "Left", "A101", False),
            devices.Controller("DEMO-RECOVERY", "Zwift Play", -57, (DFU,), bytes.fromhex("02b202"), "Recovery", None, "B202", True)]


def table(controllers):
    print("\n  #  Controller                 State                     Signal")
    print("  -- -------------------------- ------------------------- ------")
    for i, c in enumerate(controllers, 1):
        title = f"{c.side or 'Side unknown'} {c.suffix or ''}".strip()
        if c.mode == "Other / unconfirmed model":
            title = clean(c.name)[:26]
        state = c.mode if c.eligible or c.mode == "Normal" else "Inspect only"
        print(f"  {i:<2} {title:<26} {state:<25} {c.rssi} dBm")
        print(f"     ID: {clean(c.address)}")
    if any(c.mode == "Recovery" for c in controllers):
        print("\n  Recovery mode may hide left/right. Match the last four characters in")
        print("  Companion or on the device label; signal strength cannot identify a side.")


def prompt(message):
    try:
        return input(message).strip()
    except EOFError:
        raise RecoveryError("Input ended. Nothing further was sent.") from None


def normalize_path(path):
    if len(path) > 1 and path[0] == path[-1] and path[0] in "\"'":
        return path[1:-1]
    if platform.system() != "Windows" and "\\ " in path:
        try:
            parts = shlex.split(path)
            if len(parts) == 1:
                return parts[0]
        except ValueError:
            pass
    return path


def select(controllers):
    answer = prompt("\nChoose a controller number, or q to quit: ")
    if answer.lower() in ("q", "quit", ""):
        return None
    try:
        index = int(answer) - 1
        if not 0 <= index < len(controllers):
            raise ValueError
        return controllers[index]
    except ValueError:
        raise RecoveryError("That number is not in the list. Run the command again to choose a controller.") from None


def progress(event, details):
    if event == "preflight":
        print("\nRechecking the selected controller...")
    elif event == "signed_header_accepted_by_controller":
        print("Controller accepted the signed firmware. Keep it powered and nearby.")
    elif event == "transfer_progress":
        percent = details["percent"]
        print(f"  [{'#' * (percent // 5):.<20}] {percent:3}%  ({details['bytes']:,}/{details['total']:,} bytes)", flush=True)
    elif event == "verifying_reboot":
        print("Transfer finished. Waiting for reboot and reading the installed version (up to 90 seconds)...", flush=True)
    elif event == "recovery_verified":
        print(f"\nVerified: {details['side']} {details['suffix']} is running firmware {details['version']}.")
        print("Next: connect it in Zwift and test the buttons.")
    elif event == "stopped":
        print("\nStopped: " + clean(details["message"]))


def explain_empty():
    print("\nNo matching Bluetooth devices were found.")
    print("Turn the controller on, keep it nearby, and close Zwift and Companion.")
    print("A device with no light and no Bluetooth signal cannot be recovered by this tool.")


def print_inspection(result):
    values = result["values"]
    print("\nRead-only device details:")
    for key in ("firmware", "serial", "hardware", "battery"):
        print(f"  {key.capitalize()}: {clean(values.get(key, 'Not reported'))}")
    if not values:
        print("  Recovery firmware often does not expose normal device information.")
    print("  Services: " + ", ".join(result["services"]))


async def execute(args):
    if args.command == "firmware":
        firmware = load(args.path)
        print(json.dumps(firmware.record(), indent=2))
        print("Valid supported application. No Bluetooth connection was made.")
        return 0
    if args.command == "doctor":
        print(f"System: {platform.system()} | Python: {platform.python_version()}")
        print("Checking Bluetooth with a 5-second read-only scan...")
        found = await devices.scan(5)
        print(f"Bluetooth scan completed; {len(found)} relevant device(s) visible.")
        return 0
    if args.demo:
        if not getattr(args, "json", False):
            print("DEMO: fictional devices; no Bluetooth access or firmware writes.")
        controllers = demo_devices()
    else:
        if not getattr(args, "json", False):
            print(f"Scanning for {args.seconds} seconds. Keep controllers nearby; close Zwift and Companion.", flush=True)
        controllers = await devices.scan(args.seconds)
    if getattr(args, "json", False):
        print(json.dumps([c.record() for c in controllers], indent=2))
        return 0
    if not controllers:
        explain_empty()
        return 1
    table(controllers)
    if args.command == "scan":
        if args.details:
            print(json.dumps([c.record() for c in controllers], indent=2))
        return 0
    if args.demo:
        print("\nIn a live session, choose a controller to inspect or recover it.")
        print("Recovery requires a supported local firmware file and typing FLASH plus its suffix.")
        return 0
    target = devices.choose_identifier(controllers, args.device) if args.device else select(controllers)
    if target is None:
        print("Cancelled. No firmware was sent.")
        return 0
    if args.command == "inspect":
        print_inspection(await devices.inspect(target))
        return 0
    if not target.eligible:
        print_inspection(await devices.inspect(target))
        print("\nThis device is not an eligible Play recovery target. No firmware was sent.")
        return 0
    action = "r" if args.command == "recover" else prompt("\n[i] Inspect (read-only), [r] Recover, [q] Quit: ").lower()
    if action == "i":
        print_inspection(await devices.inspect(target))
        return 0
    if action != "r":
        print("Cancelled. No firmware was sent.")
        return 0
    label = None
    if target.side is None:
        side = prompt("Optional label for this controller: [l] Left, [r] Right, Enter if unknown: ").lower()
        if side not in ("", "l", "r"):
            raise RecoveryError("Use l, r, or leave the side unknown. Nothing was sent.")
        label = {"l": "Left (user identified)", "r": "Right (user identified)"}.get(side)
    print("\nRecovery is experimental. It can leave a controller unusable.")
    print("Use it only for your Zwift Play already stuck in recovery mode.")
    print("This version supports only the documented 2.0.1 application; firmware is not included.")
    path = args.firmware or prompt("Path to your firmware ZIP or folder (drag it into this terminal): ")
    firmware = load(normalize_path(path))
    print(f"\nSelected: {clean(label or 'Side unknown')} {target.suffix}")
    print(f"Device ID: {clean(target.address)}")
    print(f"Firmware: {firmware.version}, {len(firmware.image):,} bytes; hash and signatures checked.")
    print("Only this controller's application will be written. Keep it powered until verification finishes.")
    required = confirmation_text(target)
    confirmation = prompt(f"Type {required} to start, or press Enter to cancel: ")
    if confirmation != required:
        print("Cancelled. No firmware was sent.")
        return 0
    session = Session(args.reports, progress)
    print("Local diagnostic report: " + str(session.folder))
    result = await recover(target, firmware, confirmation, session, label)
    print("Report saved: " + str(session.folder / "result.json"))
    if not result["recovered"]:
        print("Recovery was not verified. Check the report before any further attempt.")
        return 2
    return 0


def parser():
    root = argparse.ArgumentParser(description="Find and inspect Zwift Play controllers; guided experimental recovery.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--demo", action="store_true", help="Preview the wizard without Bluetooth or firmware")
    root.set_defaults(command="wizard", seconds=30, device=None, firmware=None,
                      reports=str(Path.home() / ".zwift-play-recovery" / "reports"), json=False)
    commands = root.add_subparsers(dest="command")
    for name in ("wizard", "scan", "inspect", "recover"):
        sub = commands.add_parser(name, help={"wizard": "Guided scan and selection", "scan": "Read-only discovery",
                                              "inspect": "Read-only GATT details", "recover": "Recover one selected controller"}[name])
        sub.add_argument("--seconds", type=seconds, default=30)
        sub.add_argument("--demo", action="store_true", default=argparse.SUPPRESS)
        if name == "scan":
            sub.add_argument("--json", action="store_true")
            sub.add_argument("--details", action="store_true", help="Include IDs, RSSI, services and advertisement data")
        if name in ("wizard", "inspect", "recover"):
            sub.add_argument("--device", help="Exact device ID or an unambiguous four-character suffix")
        if name in ("wizard", "recover"):
            sub.add_argument("--firmware", help="Local Nordic ZIP or application.bin/application.dat folder")
            sub.add_argument("--reports", default=str(Path.home() / ".zwift-play-recovery" / "reports"))
    firmware = commands.add_parser("firmware", help="Check local firmware without connecting to Bluetooth")
    firmware.add_argument("path")
    commands.add_parser("doctor", help="Check Python and Bluetooth access without writes")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    args.command = args.command or "wizard"
    if args.demo and args.command in ("doctor", "firmware"):
        print("Use --demo with wizard, scan, inspect, or recover. Nothing was connected.", file=sys.stderr)
        return 2
    if not sys.stdin.isatty() and args.command in ("wizard", "recover") and not args.demo:
        print("Use an interactive terminal for recovery. For read-only output use: zwift-play scan --json", file=sys.stderr)
        return 2
    try:
        return asyncio.run(execute(args))
    except KeyboardInterrupt:
        print("\nStopped. If a transfer had started, its state may be uncertain. No automatic retry.", file=sys.stderr)
        return 130
    except Exception as error:
        message = str(error) or "The operation timed out."
        print("\nCould not continue: " + clean(message), file=sys.stderr)
        if not isinstance(error, RecoveryError):
            print("Check Bluetooth is on and this terminal has Bluetooth permission.", file=sys.stderr)
            if platform.system() == "Darwin":
                print("macOS: System Settings > Privacy & Security > Bluetooth.", file=sys.stderr)
            elif platform.system() == "Linux":
                print("Linux: check BlueZ is running and the adapter is available.", file=sys.stderr)
        return 2
