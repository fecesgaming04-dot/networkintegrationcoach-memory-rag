#!/usr/bin/env python
"""Generate a balanced synthetic phone-to-laptop networking coaching dataset."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


TOPICS = [
    "ADB",
    "WiFi Direct",
    "Bluetooth PAN",
    "Screen Mirroring",
    "File Sharing",
    "Troubleshooting",
    "Network Basics",
]

LEVELS = ["beginner", "intermediate", "advanced"]
CELLS = [(topic, level) for topic in TOPICS for level in LEVELS]


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total += block.count(b"\n")
    return total


def adb_output(level: str, seq: int) -> str:
    remote = ["/sdcard/Download/report.txt", "/sdcard/DCIM/Camera/latest.jpg", "/sdcard/Documents/log.txt"][seq % 3]
    local = f"C:\\PhonePulls\\batch_{seq % 100:02d}"
    if level == "beginner":
        return (
            "Goal: pull one Android file to Windows with visible failures.\n"
            "Steps: enable USB debugging, run `adb devices`, accept the phone prompt, then pull the file.\n"
            f"```powershell\nNew-Item -ItemType Directory -Force -Path \"{local}\" | Out-Null\n"
            f"adb pull \"{remote}\" \"{local}\"\nif ($LASTEXITCODE -ne 0) {{ throw \"adb pull failed\" }}\n```\n"
            "Why: `adb devices` proves the bridge is authorized, and `$LASTEXITCODE` prevents a failed copy from looking successful."
        )
    if level == "intermediate":
        return (
            "Goal: pull over wireless ADB after USB authorization.\n"
            "Steps: connect USB once, run `adb tcpip 5555`, find the phone IP, then connect by IP.\n"
            f"```powershell\nadb tcpip 5555\nadb connect 192.168.1.{20 + seq % 80}:5555\n"
            f"adb pull \"{remote}\" \"{local}\"\nif ($LASTEXITCODE -ne 0) {{ Write-Error \"wireless adb pull failed\" }}\n```\n"
            "Why: USB is used only to trust the laptop; TCP mode lets ADB work on the same WiFi."
        )
    return (
        "Goal: run a resilient ADB pull loop with logging and retry behavior.\n"
        f"```powershell\n$Remote = \"{remote}\"\n$LocalDir = \"{local}\"\nNew-Item -ItemType Directory -Force -Path $LocalDir | Out-Null\n"
        "while ($true) {\n  try {\n    adb get-state | Out-Null\n    if ($LASTEXITCODE -ne 0) { throw \"ADB device not ready\" }\n"
        "    adb pull $Remote $LocalDir\n    if ($LASTEXITCODE -ne 0) { throw \"adb pull failed with exit code $LASTEXITCODE\" }\n"
        "    Write-Host \"Pulled $Remote at $(Get-Date -Format s)\"\n  } catch { Write-Warning $_.Exception.Message }\n"
        "  Start-Sleep -Seconds 5\n}\n```\nWhy: each command is checked, so cable drops, authorization loss, and missing files are reported instead of hidden."
    )


def wifi_direct_output(level: str, seq: int) -> str:
    port = 7000 + (seq % 200)
    if level == "beginner":
        return (
            "Goal: confirm the Windows laptop can participate in WiFi Direct.\n"
            "```powershell\nnetsh wlan show drivers | Select-String \"Wi-Fi Direct\"\nGet-NetAdapter | Sort-Object Status,Name\n```\n"
            "Why: WiFi Direct depends on the wireless driver exposing a virtual adapter; the check tells you if Windows can form a peer link."
        )
    if level == "intermediate":
        return (
            "Goal: test a WiFi Direct or hotspot peer path without guessing.\n"
            f"```powershell\n$PhoneIp = \"192.168.49.{2 + seq % 50}\"\nTest-Connection $PhoneIp -Count 2\n"
            f"Test-NetConnection $PhoneIp -Port {port}\n```\n"
            "Why: ping proves layer-3 reachability, while `Test-NetConnection` proves the app port is reachable."
        )
    return (
        "Goal: serve a diagnostic file to the phone over the peer network.\n"
        f"```powershell\n$Port = {port}\n$Root = \"C:\\PhoneShare\"\nNew-Item -ItemType Directory -Force -Path $Root | Out-Null\n"
        "python -m http.server $Port --directory $Root\n```\n"
        "Why: a tiny HTTP server removes SMB and pairing variables; if the phone browser opens the URL, the WiFi Direct route works."
    )


def bluetooth_pan_output(level: str, seq: int) -> str:
    if level == "beginner":
        return (
            "Goal: find the Bluetooth PAN adapter and check whether it has an IP address.\n"
            "```powershell\nGet-NetAdapter | Where-Object Name -like \"*Bluetooth*\"\nipconfig /all\n```\n"
            "Why: Bluetooth PAN behaves like a slow Ethernet link; it still needs an adapter, address, and route."
        )
    if level == "intermediate":
        return (
            "Goal: verify a PAN connection after pairing and tethering.\n"
            f"```powershell\n$PhoneGateway = \"192.168.44.{1 + seq % 5}\"\nTest-Connection $PhoneGateway -Count 2\nroute print\n```\n"
            "Why: the gateway ping confirms the phone is the PAN router, and the route table shows whether traffic will use it."
        )
    return (
        "Goal: capture useful PAN troubleshooting state for a repeatable report.\n"
        "```powershell\n$Out = \"C:\\PhoneDiagnostics\\bluetooth-pan.txt\"\nNew-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null\n"
        "Get-NetAdapter | Out-File $Out\nipconfig /all | Out-File $Out -Append\nGet-NetRoute | Out-File $Out -Append\n```\n"
        "Why: adapter, address, and route data together show whether the failure is pairing, DHCP, or routing."
    )


def screen_mirroring_output(level: str, seq: int) -> str:
    bitrate = [4, 8, 12][seq % 3]
    if level == "beginner":
        return (
            "Goal: mirror an Android screen with scrcpy after ADB is authorized.\n"
            f"```powershell\nadb devices\nscrcpy --max-size 1280 --video-bit-rate {bitrate}M\n```\n"
            "Why: scrcpy uses ADB transport, so fixing ADB authorization usually fixes mirroring startup."
        )
    if level == "intermediate":
        return (
            "Goal: mirror over WiFi after switching ADB to TCP mode.\n"
            f"```powershell\nadb tcpip 5555\nadb connect 192.168.1.{30 + seq % 60}:5555\nscrcpy --tcpip --video-bit-rate {bitrate}M\n```\n"
            "Why: TCP mirroring avoids the cable, but it needs the phone and laptop on a reachable network."
        )
    return (
        "Goal: collect mirroring failure details without losing the original error.\n"
        "```powershell\ntry {\n  adb get-state | Out-Null\n  if ($LASTEXITCODE -ne 0) { throw \"ADB is not ready\" }\n"
        f"  scrcpy --max-fps 30 --video-bit-rate {bitrate}M 2>&1 | Tee-Object C:\\PhoneDiagnostics\\scrcpy.log\n"
        "} catch { Write-Error $_.Exception.Message }\n```\n"
        "Why: logging stderr keeps codec, firewall, and authorization errors available after the window closes."
    )


def file_sharing_output(level: str, seq: int) -> str:
    name = f"PhoneDrop{seq % 50:02d}"
    if level == "beginner":
        return (
            "Goal: create a temporary Windows folder that a phone can download from in a browser.\n"
            f"```powershell\n$Root = \"C:\\{name}\"\nNew-Item -ItemType Directory -Force -Path $Root | Out-Null\n"
            "python -m http.server 8080 --directory $Root\n```\n"
            "Why: browser-based HTTP avoids account, SMB, and Bluetooth profile issues during first tests."
        )
    if level == "intermediate":
        return (
            "Goal: copy a folder to a shared Windows location with retry behavior.\n"
            f"```batch\nrobocopy C:\\Incoming C:\\{name} /E /R:2 /W:3 /NFL /NDL\nif errorlevel 8 exit /b %errorlevel%\n```\n"
            "Why: robocopy exit codes below 8 can be normal copy states; 8 or higher means a real failure."
        )
    return (
        "Goal: create an SMB share for controlled phone file access on trusted WiFi.\n"
        f"```powershell\n$Path = \"C:\\{name}\"\nNew-Item -ItemType Directory -Force -Path $Path | Out-Null\n"
        f"New-SmbShare -Name \"{name}\" -Path $Path -ChangeAccess $env:USERNAME\nGet-SmbShare -Name \"{name}\"\n```\n"
        "Why: the share name and NTFS permissions both matter; the command makes both explicit."
    )


def troubleshooting_output(level: str, seq: int) -> str:
    if level == "beginner":
        return (
            "Goal: reset the most common ADB failure path.\n"
            "```powershell\nadb kill-server\nadb start-server\nadb devices\n```\n"
            "Why: restarting the server clears stale USB and TCP sessions, then `devices` shows whether the phone is unauthorized or offline."
        )
    if level == "intermediate":
        return (
            "Goal: distinguish firewall, routing, and service failures.\n"
            f"```powershell\n$PhoneIp = \"192.168.1.{20 + seq % 80}\"\nTest-Connection $PhoneIp -Count 2\n"
            "Test-NetConnection $PhoneIp -Port 5555\nGet-NetFirewallProfile\n```\n"
            "Why: reachability, port state, and firewall profile point to different fixes."
        )
    return (
        "Goal: produce a compact troubleshooting bundle for phone-laptop networking.\n"
        "```powershell\n$Out = \"C:\\PhoneDiagnostics\\network-bundle.txt\"\nNew-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null\n"
        "adb devices -l | Out-File $Out\nipconfig /all | Out-File $Out -Append\nroute print | Out-File $Out -Append\nnetstat -ano | Out-File $Out -Append\n```\n"
        "Why: this captures USB state, addresses, routes, and listening ports in one reproducible artifact."
    )


def network_basics_output(level: str, seq: int) -> str:
    ip = f"192.168.{seq % 5}.{20 + seq % 80}"
    if level == "beginner":
        return (
            "Goal: check whether phone and laptop are on the same IPv4 network.\n"
            "```powershell\nipconfig\nGet-NetIPConfiguration | Select-Object InterfaceAlias,IPv4Address,IPv4DefaultGateway\n```\n"
            "Why: devices on the same subnet can usually talk directly; different subnets may need routing or hotspot mode."
        )
    if level == "intermediate":
        return (
            "Goal: trace the path from laptop to phone.\n"
            f"```powershell\nTest-Connection {ip} -Count 3\ntracert {ip}\narp -a | Select-String \"{ip}\"\n```\n"
            "Why: ping, route hops, and ARP together show whether packets reach the local network and resolve the phone."
        )
    return (
        "Goal: inspect Windows network selection when several links are active.\n"
        "```powershell\nGet-NetIPInterface | Sort-Object InterfaceMetric | Select-Object InterfaceAlias,AddressFamily,InterfaceMetric\nGet-NetRoute -AddressFamily IPv4 | Sort-Object RouteMetric | Select-Object -First 10\n```\n"
        "Why: Windows picks lower metric routes first, so WiFi, PAN, and virtual adapters can change where traffic goes."
    )


RENDERERS = {
    "ADB": adb_output,
    "WiFi Direct": wifi_direct_output,
    "Bluetooth PAN": bluetooth_pan_output,
    "Screen Mirroring": screen_mirroring_output,
    "File Sharing": file_sharing_output,
    "Troubleshooting": troubleshooting_output,
    "Network Basics": network_basics_output,
}


def build_record(index: int) -> dict[str, str]:
    topic, level = CELLS[index % len(CELLS)]
    seq = index // len(CELLS)
    verbs = ["show", "explain", "debug", "automate", "verify", "set up", "recover"]
    intent = verbs[(seq + len(topic) + len(level)) % len(verbs)]
    instruction = (
        f"[level:{level}] [topic:{topic}] {intent} a Windows 11 phone-to-laptop "
        f"networking task with real commands and explain why. Scenario {seq}."
    )
    return {
        "instruction": instruction,
        "output": RENDERERS[topic](level, seq),
        "topic": topic,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(REPO_ROOT / "data" / "network_guide_2M.jsonl"))
    parser.add_argument("--records", type=int, default=2_000_000)
    parser.add_argument("--progress-every", type=int, default=10_000)
    parser.add_argument("--sleep-every", type=int, default=50_000)
    parser.add_argument("--sleep-seconds", type=float, default=0.05)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".partial")
    progress = output.with_suffix(output.suffix + ".progress.json")

    if output.exists():
        existing_final = count_lines(output)
        if existing_final == args.records:
            print(f"complete: {output} already has {existing_final} records")
            return 0
        if existing_final > args.records:
            raise RuntimeError(f"{output} has {existing_final} lines, expected at most {args.records}")
        if not partial.exists():
            output.replace(partial)

    start = count_lines(partial)
    mode = "a" if start else "w"
    counts: dict[str, int] = {f"{topic}|{level}": 0 for topic, level in CELLS}
    for index in range(start):
        topic, level = CELLS[index % len(CELLS)]
        counts[f"{topic}|{level}"] += 1

    print(f"starting at record {start} of {args.records}")
    began = time.time()
    with partial.open(mode, encoding="utf-8", newline="\n") as handle:
        for index in range(start, args.records):
            topic, level = CELLS[index % len(CELLS)]
            record = build_record(index)
            handle.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
            counts[f"{topic}|{level}"] += 1

            written = index + 1
            if written % args.progress_every == 0 or written == args.records:
                handle.flush()
                os.fsync(handle.fileno())
                elapsed = max(time.time() - began, 0.001)
                rate = (written - start) / elapsed
                progress.write_text(
                    json.dumps(
                        {
                            "records": written,
                            "target": args.records,
                            "percent": round(written * 100 / args.records, 3),
                            "records_per_second": round(rate, 1),
                            "counts": counts,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                print(f"progress: {written}/{args.records} ({written * 100 / args.records:.2f}%) at {rate:.0f} rows/s")

            if args.sleep_every and written % args.sleep_every == 0:
                time.sleep(args.sleep_seconds)

    partial.replace(output)
    print(f"complete: wrote {args.records} records to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
