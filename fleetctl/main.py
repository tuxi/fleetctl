"""
fleetctl python-core main entry point.
Provides CLI interface for device management operations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from fleetctl.device_detector import DeviceDetector
from fleetctl.device_info import DeviceInfoCollector
from fleetctl.backup_parser import parse_backup, open_manifest_db
from fleetctl.config_writer import ConfigWriter, CloudConfiguration, create_enterprise_config
from fleetctl.wipe_manager import WipeManager, WipeOptions, quick_wipe, full_wipe_with_certificate
from fleetctl.report_generator import generate_device_report, ReportConfig
from fleetctl.usb_manager import USBDeviceManager, BulkOperationManager, create_device_manager, DeviceFilter
from fleetctl.report_generator import ReportGeneratorFactory
from fleetctl.precheck import (
    run_precheck_steps,
    generate_precheck_report,
    step_label,
    ERASE_GUIDANCE,
    WAIT_ACK_PROMPT,
)


async def cmd_detect(args):
    """Detect device information."""
    collector = DeviceInfoCollector()
    report = await collector.collect(args.udid)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


async def cmd_list_devices(args):
    """List all connected devices."""
    manager = USBDeviceManager()
    devices = await manager.enumerate()
    
    if args.json:
        print(json.dumps(devices, indent=2, ensure_ascii=False))
    else:
        for device in devices:
            print(f"{device['udid']}  {device.get('device_name', 'Unknown')}  {device.get('product_type', 'Unknown')}  {device.get('product_version', 'Unknown')}")


async def cmd_precheck(args):
    """
    Three-step manual gateway pre-check (三步手工门验证) — read-only.

    Step 1: Erase availability (can "Erase All Content and Settings" be used?)
    Step 2: Offline Setup Assistant (reached the Wi-Fi-before screen)
    Step 3: USB pairing (lockdown channel healthy)

    This tool never erases or modifies a device. With ``--confirm`` the flow
    becomes interactive: after Step 1 it prints erase guidance and, with
    ``--wait <seconds>``, polls until the device reaches the offline Setup
    Assistant state and re-runs Step 2. Audit reports can be written via
    ``--report`` / ``--report-format``.
    """
    manager = USBDeviceManager()
    devices = await manager.enumerate()

    if not devices:
        print("No devices connected.")
        return

    # Filter by UDID if provided
    if args.udid:
        devices = [d for d in devices if d["udid"] == args.udid]
        if not devices:
            print(f"Device {args.udid} not found.")
            return

    collector = DeviceInfoCollector()
    prechecks = []
    step_index = {"erase_available": 1, "setup_assistant_offline": 2, "usb_pairing": 3}

    for device in devices:
        udid = device["udid"]
        print(f"\n{'=' * 60}")
        print(f"Pre-check for device: {udid}")
        print(f"  Name: {device.get('device_name', 'Unknown')}")
        print(f"  Model: {device.get('product_type', 'Unknown')}")
        print(f"  iOS: {device.get('product_version', 'Unknown')}")
        print(f"{'=' * 60}")

        def _show_step(name, res):
            idx = step_index[name]
            print(f"\n[Step {idx}/3] Checking {name.replace('_', ' ')}...")
            print(f"  Result: {res.get('status', 'unknown')}")
            details = res.get("details")
            if isinstance(details, dict):
                for k, v in details.items():
                    print(f"    {k}: {v}")
            elif details:
                print(f"  Details: {details}")

        result = await run_precheck_steps(udid, collector, device, on_step=_show_step)
        steps = result["steps"]

        # Step 1 guidance: if erase is available but we are not yet in the
        # offline Setup Assistant window, guide the operator and optionally wait.
        if steps["erase_available"]["passed"] and not steps["setup_assistant_offline"]["passed"]:
            _print_erase_guidance()
            if getattr(args, "confirm", False):
                answer = input(WAIT_ACK_PROMPT).strip().upper()
                if answer == "READY" and getattr(args, "wait", 0) > 0:
                    print(f"  Polling up to {args.wait}s for the offline Setup Assistant state...")
                    if await _wait_for_offline_setup_assistant(collector, udid, args.wait):
                        raw2 = await collector.check_setup_assistant_offline_state(udid)
                        steps["setup_assistant_offline"] = {
                            "passed": bool(raw2.get("ready", False)),
                            "status": raw2.get("reason", "unknown"),
                            "details": raw2.get("details", {}),
                        }
                        _show_step("setup_assistant_offline", steps["setup_assistant_offline"])
                        result["overall_passed"] = all(s["passed"] for s in steps.values())
                    else:
                        print("  Timed out waiting for the offline Setup Assistant state.")

        # Summary
        overall = result["overall_passed"]
        print(f"\n{'=' * 60}")
        print(f"PRE-CHECK SUMMARY: {'PASSED' if overall else 'FAILED'}")
        print(f"{'=' * 60}")
        for key in ["erase_available", "setup_assistant_offline", "usb_pairing"]:
            mark = "[OK]" if steps[key]["passed"] else "[FAIL]"
            print(f"  {step_label(key):<26} {mark}")

        prechecks.append(result)

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))

    # Audit report (JSON / HTML)
    report_path = getattr(args, "report", None)
    if report_path:
        fmt = getattr(args, "report_format", "json") or "json"
        content = generate_precheck_report(
            prechecks,
            format=fmt,
            title=getattr(args, "title", "fleetctl Pre-check Audit Report"),
            company_name=getattr(args, "company", None),
        )
        Path(report_path).write_bytes(content)
        print(f"\nAudit report written: {report_path} ({fmt})")


def _print_erase_guidance():
    print("\n" + "-" * 60)
    print("NEXT: manual erase on the device (fleetctl does not erase devices).")
    print(ERASE_GUIDANCE)
    print("-" * 60)


async def _wait_for_offline_setup_assistant(collector, udid, timeout, interval=5.0):
    """Poll until the device reaches the offline Setup Assistant state."""
    import time as _time
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        raw = await collector.check_setup_assistant_offline_state(udid)
        if raw.get("ready"):
            return True
        await asyncio.sleep(interval)
    return False


async def cmd_parse_backup(args):
    """Parse iOS backup."""
    backup_path = Path(args.backup_path)
    if not backup_path.exists():
        print(f"Error: Backup path does not exist: {backup_path}", file=sys.stderr)
        sys.exit(1)
    
    summary = parse_backup(backup_path)
    
    if args.json:
        # Convert to dict for JSON serialization
        result = {
            "backup_path": str(summary.backup_path),
            "manifest": {
                "version": summary.manifest.version,
                "is_encrypted": summary.manifest.is_encrypted,
                "device_name": summary.manifest.device_name,
                "product_type": summary.manifest.product_type,
                "product_version": summary.manifest.product_version,
                "serial_number": summary.manifest.serial_number,
            },
            "info": {
                "device_name": summary.info.device_name,
                "product_type": summary.info.product_type,
                "product_version": summary.info.product_version,
            },
            "status": {
                "snapshot_state": summary.status.snapshot_state,
                "is_full_backup": summary.status.is_full_backup,
            },
            "apps_count": len(summary.apps),
            "total_files": summary.total_files,
            "total_size": summary.total_size,
            "is_encrypted": summary.is_encrypted,
            "errors": summary.errors,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Backup: {summary.backup_path}")
        print(f"  Device: {summary.info.device_name} ({summary.info.product_type})")
        print(f"  iOS: {summary.info.product_version} ({summary.info.build_version})")
        print(f"  Serial: {summary.info.serial_number}")
        print(f"  Encrypted: {summary.is_encrypted}")
        print(f"  Apps: {len(summary.apps)}")
        print(f"  Files: {summary.total_files}")
        print(f"  Size: {summary.total_size / (1024**3):.2f} GB")
        if summary.errors:
            print(f"  Errors: {summary.errors}")


async def cmd_wipe(args):
    """Wipe device."""
    options = WipeOptions(
        method=args.method,
        preserve_data_plan=args.preserve_data_plan,
        disallow_proximity_setup=args.disallow_proximity,
        verify_after=args.verify,
        generate_certificate=not args.no_certificate,
    )
    
    manager = WipeManager()
    result = await manager.wipe_device(args.udid, options)
    
    if args.json:
        result_dict = {
            "success": result.success,
            "method": result.method,
            "udid": result.udid,
            "message": result.message,
            "error_code": result.error_code,
            "details": result.details,
            "certificate": result.certificate,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "duration_seconds": result.duration_seconds,
        }
        print(json.dumps(result_dict, indent=2, ensure_ascii=False))
    else:
        if result.success:
            print(f"✓ Wipe successful: {result.message}")
            if result.certificate:
                print(f"Certificate generated ({len(result.certificate)} chars)")
        else:
            print(f"✗ Wipe failed: {result.message}")
            if result.error_code:
                print(f"  Error code: {result.error_code}")
        sys.exit(0 if result.success else 1)


async def cmd_report(args):
    """Generate device report from device data."""
    devices = []
    
    # Load device data from input file
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Error: Input file not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        # Handle different input formats
        if isinstance(data, list):
            devices = data
        elif isinstance(data, dict) and "devices" in data:
            devices = data["devices"]
        else:
            devices = [data]
    else:
        # Collect from connected devices
        manager = USBDeviceManager()
        connected_devices = await manager.enumerate()
        
        if not connected_devices:
            print("No devices connected and no input file provided.")
            print("Use --input to specify a JSON file with device data.")
            sys.exit(1)
        
        # Filter by UDID if provided
        if hasattr(args, 'udid') and args.udid:
            connected_devices = [d for d in connected_devices if d['udid'] == args.udid]
        
        # Collect detailed info for each device
        collector = DeviceInfoCollector()
        for device in connected_devices:
            report = await collector.collect(device['udid'])
            devices.append(report.to_dict())
    
    if not devices:
        print("No device data to report.")
        sys.exit(1)
    
    # Generate report
    config = ReportConfig(
        title=args.title,
        company_name=args.company,
    )
    
    try:
        output = ReportGeneratorFactory.generate_report(
            devices=devices,
            format=args.format,
            config=config,
            output_path=Path(args.output) if args.output else None
        )
        
        if args.output:
            print(f"Report generated: {args.output}")
        else:
            # Print to stdout for text formats
            if args.format in ["json", "csv", "html"]:
                print(output.decode("utf-8"))
            else:
                print(f"Report generated ({len(output)} bytes). Use --output to save to file.")
                
    except Exception as e:
        print(f"Error generating report: {e}", file=sys.stderr)
        sys.exit(1)


async def cmd_filter(args):
    """Filter devices by various criteria."""
    # Load device data
    devices = []
    
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Error: Input file not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        
        with open(input_path, 'r') as f:
            data = json.load(f)
        
        if isinstance(data, list):
            devices = data
        elif isinstance(data, dict) and "devices" in data:
            devices = data["devices"]
        else:
            devices = [data]
    else:
        # Collect from connected devices
        manager = USBDeviceManager()
        connected_devices = await manager.enumerate()
        
        if not connected_devices:
            print("No devices connected and no input file provided.")
            sys.exit(1)
        
        # Collect detailed info for each device
        collector = DeviceInfoCollector()
        for device in connected_devices:
            report = await collector.collect(device['udid'])
            devices.append(report.to_dict())
    
    if not devices:
        print("No device data to filter.")
        sys.exit(1)
    
    # Apply filters
    filtered = devices
    
    if args.product_type:
        filtered = DeviceFilter.by_product_type(filtered, args.product_type)
    
    if args.min_ios or args.max_ios:
        filtered = DeviceFilter.by_ios_version(filtered, args.min_ios, args.max_ios)
    
    if args.chip:
        filtered = DeviceFilter.by_chip(filtered, args.chip)
    
    if args.supervised:
        filtered = DeviceFilter.supervised_only(filtered)
    
    if args.unsupervised:
        filtered = DeviceFilter.unsupervised_only(filtered)
    
    if args.with_errors:
        filtered = DeviceFilter.with_errors(filtered)
    
    if args.without_errors:
        filtered = DeviceFilter.without_errors(filtered)
    
    if args.min_free_gb or args.max_used_percent:
        filtered = DeviceFilter.by_storage(filtered, args.min_free_gb, args.max_used_percent)
    
    # Output results
    if args.json:
        print(json.dumps(filtered, indent=2, ensure_ascii=False))
    else:
        print(f"Filtered {len(filtered)} of {len(devices)} devices:")
        for device in filtered:
            identity = device.get("identity", {})
            status = device.get("status", {})
            print(f"  {identity.get('udid', 'Unknown')[:8]}...  {identity.get('product_type', 'Unknown')}  iOS {identity.get('product_version', 'Unknown')}  Chip: {device.get('metadata', {}).get('chip', 'Unknown')}  Supervised: {status.get('is_supervised', 'Unknown')}")


async def cmd_bulk(args):
    """Run bulk operations on multiple devices."""
    # Load device data
    manager = USBDeviceManager()
    connected_devices = await manager.enumerate()
    
    if not connected_devices:
        print("No devices connected.")
        sys.exit(1)
    
    # Filter by UDID if provided
    if args.udid:
        connected_devices = [d for d in connected_devices if d['udid'] == args.udid]
        if not connected_devices:
            print(f"Device {args.udid} not found.")
            return
    
    udids = [d['udid'] for d in connected_devices]
    print(f"Running bulk operation on {len(udids)} device(s)...")
    
    bulk_manager = BulkOperationManager(manager)
    
    if args.operation == "detect":
        async def operation(udid):
            collector = DeviceInfoCollector()
            report = await collector.collect(udid)
            return report.to_dict()
        
        results = await bulk_manager.run_on_all(
            operation,
            udids=udids,
            max_concurrent=args.max_concurrent,
            progress_callback=lambda u, c, t: print(f"  Progress: {c}/{t} - {u[:8]}...") if args.progress else None,
            use_tqdm=args.progress,
            tqdm_desc="Detecting devices",
            resume=args.resume,
        )
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            for udid, result in results.items():
                if result["success"]:
                    print(f"  ✓ {udid[:8]}...: Success")
                else:
                    print(f"  ✗ {udid[:8]}...: {result.get('error', 'Failed')}")
    
    elif args.operation == "wipe":
        if not args.confirm:
            print("ERROR: Wipe operation requires --confirm flag")
            sys.exit(1)
        
        # Interactive safety confirmation - mandatory even with --confirm flag
        print("\n" + "="*60)
        print("⚠️  WARNING: DESTRUCTIVE OPERATION - DATA WILL BE PERMANENTLY ERASED")
        print("="*60)
        print(f"Devices to wipe: {len(udids)}")
        for d in udids:
            device_info = next((dev for dev in connected_devices if dev['udid'] == d), {})
            name = device_info.get('device_name', 'Unknown')
            model = device_info.get('product_type', 'Unknown')
            print(f"  - {d[:8]}... ({name}, {model})")
        print("="*60)
        print("This will:")
        print("  • PERMANENTLY DESTROY all data on the device(s)")
        print("  • Reset device(s) to factory state (Setup Assistant)")
        print("  • Data CANNOT be recovered (NIST 800-88 Purge)")
        print("="*60)
        
        # Require explicit typed confirmation
        confirm_text = input('\nType "WIPE" (all caps) to confirm: ').strip()
        if confirm_text != "WIPE":
            print("Aborted: confirmation text does not match.")
            sys.exit(1)
        
        print("\nProceeding with wipe in 3 seconds... (Ctrl+C to cancel)")
        import time
        for i in range(3, 0, -1):
            print(f"  {i}...")
            time.sleep(1)
        print()
        
        options = WipeOptions(
            method=args.method,
            preserve_data_plan=args.preserve_data_plan,
            disallow_proximity_setup=args.disallow_proximity,
            verify_after=args.verify,
            generate_certificate=not args.no_certificate,
        )
        
        wipe_manager = WipeManager()
        
        async def operation(udid):
            result = await wipe_manager.wipe_device(udid, options)
            return {
                "success": result.success,
                "message": result.message,
                "certificate": result.certificate,
            }
        
        results = await bulk_manager.run_sequential(
            operation,
            udids=udids,
            progress_callback=lambda u, c, t: print(f"  Progress: {c}/{t} - {u[:8]}...") if args.progress else None,
            use_tqdm=args.progress,
            tqdm_desc="Wiping devices",
            resume=args.resume,
        )
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            for udid, result in results.items():
                if result["success"]:
                    # result is wrapped in {"success": True, "result": {...}}
                    inner = result.get("result", {})
                    print(f"  ✓ {udid[:8]}...: {inner.get('message', 'Success')}")
                else:
                    print(f"  ✗ {udid[:8]}...: {result.get('error', 'Failed')}")
    
    elif args.operation == "precheck":
        precheck_collector = DeviceInfoCollector()

        async def operation(udid):
            return await run_precheck_steps(udid, precheck_collector)
        
        results = await bulk_manager.run_on_all(
            operation,
            udids=udids,
            max_concurrent=args.max_concurrent,
            progress_callback=lambda u, c, t: print(f"  Progress: {c}/{t} - {u[:8]}...") if args.progress else None,
            use_tqdm=args.progress,
            tqdm_desc="Pre-checking devices",
            resume=args.resume,
        )
        
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            for udid, result in results.items():
                if result["success"]:
                    data = result["result"]
                    status = "PASSED" if data["overall_passed"] else "FAILED"
                    print(f"  {udid[:8]}...: {status}")
                    for step_name, step_data in data["steps"].items():
                        print(f"    {step_name}: {step_data['status']}")
                else:
                    print(f"  ✗ {udid[:8]}...: {result.get('error', 'Failed')}")


async def cmd_monitor(args):
    """Monitor device connections."""
    manager = await create_device_manager()
    
    def callback(udid, state):
        print(f"Device {udid}: {state.value}")
    
    manager.add_callback(callback)
    
    print("Monitoring device connections... Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping monitor...")
    finally:
        await manager.stop_monitoring()


def main():
    parser = argparse.ArgumentParser(
        prog="fleetctl",
        description="fleetctl - Cross-platform compliant device management toolkit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # detect command
    detect_parser = subparsers.add_parser("detect", help="Detect device information")
    detect_parser.add_argument("udid", help="Device UDID")
    detect_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # list-devices command
    list_parser = subparsers.add_parser("list", help="List connected devices")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # parse-backup command
    backup_parser = subparsers.add_parser("parse-backup", help="Parse iOS backup")
    backup_parser.add_argument("backup_path", help="Path to backup directory")
    backup_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # wipe command
    wipe_parser = subparsers.add_parser("wipe", help="Wipe device (compliant)")
    wipe_parser.add_argument("udid", help="Device UDID")
    wipe_parser.add_argument("--method", choices=["quick", "full", "nist_clear", "nist_purge", "nist_destroy"], default="full", help="Wipe method")
    wipe_parser.add_argument("--preserve-data-plan", action="store_true", help="Preserve eSIM data plan")
    wipe_parser.add_argument("--disallow-proximity", action="store_true", help="Disallow proximity setup after wipe")
    wipe_parser.add_argument("--no-verify", action="store_false", dest="verify", help="Skip verification after wipe")
    wipe_parser.add_argument("--no-certificate", action="store_true", help="Don't generate wipe certificate")
    wipe_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # precheck command (三步手工门验证)
    precheck_parser = subparsers.add_parser("precheck", help="Three-step manual gateway verification (三步手工门验证)")
    precheck_parser.add_argument("--udid", help="Device UDID (optional, checks all if not specified)")
    precheck_parser.add_argument("--json", action="store_true", help="Output as JSON")
    precheck_parser.add_argument("--confirm", action="store_true", help="Enable interactive guided erase flow (prompts for READY)")
    precheck_parser.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="With --confirm: poll up to SECONDS for the offline Setup Assistant state")
    precheck_parser.add_argument("--report", metavar="PATH", help="Write an audit report to PATH")
    precheck_parser.add_argument("--report-format", choices=["json", "html"], default="json", help="Audit report format (default: json)")
    precheck_parser.add_argument("--title", default="fleetctl Pre-check Audit Report", help="Audit report title")
    precheck_parser.add_argument("--company", help="Company name for the audit report")
    
    # report command
    report_parser = subparsers.add_parser("report", help="Generate device report")
    report_parser.add_argument("--input", help="Input JSON file with device data")
    report_parser.add_argument("--udid", help="Device UDID (optional, collects from all connected if not specified)")
    report_parser.add_argument("--format", choices=["json", "csv", "html", "pdf"], default="html")
    report_parser.add_argument("--output", help="Output file path")
    report_parser.add_argument("--title", default="Device Fleet Report")
    report_parser.add_argument("--company", help="Company name for report")
    
    # monitor command
    monitor_parser = subparsers.add_parser("monitor", help="Monitor device connections")
    
    # filter command
    filter_parser = subparsers.add_parser("filter", help="Filter devices by criteria")
    filter_parser.add_argument("--input", help="Input JSON file with device data")
    filter_parser.add_argument("--product-type", help="Filter by product type (e.g., iPhone15,2)")
    filter_parser.add_argument("--min-ios", help="Minimum iOS version (e.g., 17.0)")
    filter_parser.add_argument("--max-ios", help="Maximum iOS version (e.g., 17.9)")
    filter_parser.add_argument("--chip", help="Filter by chip (e.g., A16, M1)")
    filter_parser.add_argument("--supervised", action="store_true", help="Filter supervised devices only")
    filter_parser.add_argument("--unsupervised", action="store_true", help="Filter unsupervised devices only")
    filter_parser.add_argument("--with-errors", action="store_true", help="Filter devices with errors")
    filter_parser.add_argument("--without-errors", action="store_true", help="Filter devices without errors")
    filter_parser.add_argument("--min-free-gb", type=float, help="Minimum free storage in GB")
    filter_parser.add_argument("--max-used-percent", type=float, help="Maximum used storage percentage")
    filter_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    # bulk command
    bulk_parser = subparsers.add_parser("bulk", help="Run bulk operations on multiple devices")
    bulk_parser.add_argument("operation", choices=["detect", "wipe", "precheck"], help="Operation to run")
    bulk_parser.add_argument("--udid", help="Device UDID (optional, runs on all if not specified)")
    bulk_parser.add_argument("--max-concurrent", type=int, default=4, help="Max concurrent operations")
    bulk_parser.add_argument("--progress", action="store_true", help="Show progress")
    bulk_parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    bulk_parser.add_argument("--json", action="store_true", help="Output as JSON")
    # Wipe-specific options
    bulk_parser.add_argument("--confirm", action="store_true", help="Confirm wipe operation (required for wipe)")
    bulk_parser.add_argument("--method", choices=["quick", "full", "nist_clear", "nist_purge", "nist_destroy"], default="full", help="Wipe method")
    bulk_parser.add_argument("--preserve-data-plan", action="store_true", help="Preserve eSIM data plan")
    bulk_parser.add_argument("--disallow-proximity", action="store_true", help="Disallow proximity setup after wipe")
    bulk_parser.add_argument("--no-verify", action="store_false", dest="verify", help="Skip verification after wipe")
    bulk_parser.add_argument("--no-certificate", action="store_true", help="Don't generate wipe certificate")
    
    args = parser.parse_args()
    
    # Run async command
    if args.command == "detect":
        _run(cmd_detect(args))
    elif args.command == "list":
        _run(cmd_list_devices(args))
    elif args.command == "precheck":
        _run(cmd_precheck(args))
    elif args.command == "parse-backup":
        _run(cmd_parse_backup(args))
    elif args.command == "wipe":
        _run(cmd_wipe(args))
    elif args.command == "report":
        _run(cmd_report(args))
    elif args.command == "filter":
        _run(cmd_filter(args))
    elif args.command == "bulk":
        _run(cmd_bulk(args))
    elif args.command == "monitor":
        _run(cmd_monitor(args))
    else:
        parser.print_help()
        sys.exit(1)


def _quiet_asyncio_exceptions(loop, context):
    """Suppress benign, noisy asyncio warnings from best-effort probes.

    Opening an optional lockdown service (e.g. MobileConfigService) on a device
    state where it is unavailable raises inside pymobiledevice3, which can leave
    an internal Future whose exception is never retrieved. We already catch and
    report the underlying condition, so the GC-time "never retrieved" warning is
    just noise. Everything else goes to the default handler.
    """
    message = context.get("message", "")
    if "never retrieved" in message:
        return
    loop.default_exception_handler(context)


def _run(coro):
    """Run a CLI coroutine with a quieter asyncio exception handler."""
    async def _main():
        asyncio.get_running_loop().set_exception_handler(_quiet_asyncio_exceptions)
        return await coro
    return asyncio.run(_main())


if __name__ == "__main__":
    main()