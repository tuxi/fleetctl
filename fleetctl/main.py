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
    Three-step manual gateway verification (三步手工门验证).
    
    Step 1: Can "Erase All Content and Settings" (抹掉所有内容和设置)
    Step 2: Offline - Can enter Setup Assistant to Wi-Fi selection screen
    Step 3: USB pairing works normally
    """
    manager = USBDeviceManager()
    devices = await manager.enumerate()
    
    if not devices:
        print("No devices connected.")
        return
    
    # Filter by UDID if provided
    if args.udid:
        devices = [d for d in devices if d['udid'] == args.udid]
        if not devices:
            print(f"Device {args.udid} not found.")
            return
    
    collector = DeviceInfoCollector()
    
    for device in devices:
        udid = device['udid']
        print(f"\n{'='*60}")
        print(f"Pre-check for device: {udid}")
        print(f"  Name: {device.get('device_name', 'Unknown')}")
        print(f"  Model: {device.get('product_type', 'Unknown')}")
        print(f"  iOS: {device.get('product_version', 'Unknown')}")
        print(f"{'='*60}")
        
        # Step 1: Check if "Erase All Content and Settings" is available
        print("\n[Step 1/3] Checking 'Erase All Content and Settings' availability...")
        step1_result = await check_erase_availability(udid)
        print(f"  Result: {step1_result['status']}")
        if step1_result['details']:
            print(f"  Details: {step1_result['details']}")
        
        # Step 2: Check if device can enter Setup Assistant offline (automated)
        print("\n[Step 2/3] Checking Setup Assistant entry (offline)...")
        step2_raw = await collector.check_setup_assistant_offline_state(udid)
        # Convert new format to expected format
        step2_result = {
            "passed": step2_raw.get("ready", False),
            "status": step2_raw.get("reason", "unknown"),
            "details": step2_raw.get("details", {})
        }
        print(f"  Result: {step2_result['status']}")
        if step2_result['details']:
            # Print key details
            details = step2_result['details']
            if isinstance(details, dict):
                for k, v in details.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  Details: {details}")
        
        # Step 3: Check USB pairing
        print("\n[Step 3/3] Checking USB pairing...")
        step3_result = await check_usb_pairing(udid)
        print(f"  Result: {step3_result['status']}")
        if step3_result['details']:
            print(f"  Details: {step3_result['details']}")
        
        # Summary
        all_passed = all(r['passed'] for r in [step1_result, step2_result, step3_result])
        print(f"\n{'='*60}")
        print(f"PRE-CHECK SUMMARY: {'PASSED' if all_passed else 'FAILED'}")
        print(f"{'='*60}")
        print(f"  Step 1 (Erase Available): {'✓' if step1_result['passed'] else '✗'}")
        print(f"  Step 2 (Setup Assistant): {'✓' if step2_result['passed'] else '✗'}")
        print(f"  Step 3 (USB Pairing):     {'✓' if step3_result['passed'] else '✗'}")
        
        if args.json:
            result = {
                "udid": udid,
                "device_name": device.get('device_name'),
                "product_type": device.get('product_type'),
                "product_version": device.get('product_version'),
                "steps": {
                    "erase_available": step1_result,
                    "setup_assistant_offline": step2_result,
                    "usb_pairing": step3_result,
                },
                "overall_passed": all_passed,
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))


async def check_erase_availability(udid: str) -> dict:
    """Step 1: Check if 'Erase All Content and Settings' is available."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.mobile_config import MobileConfigService
        
        lockdown = await create_using_usbmux(serial=udid)
        vals = lockdown.all_values or {}
        
        # Check activation state - if already in Setup Assistant, erase is available
        activation_state = vals.get("ActivationState", "")
        
        # Check if device is supervised (MDM may restrict erase)
        is_supervised = False
        try:
            async with MobileConfigService(ld) as mc:
                cc = await mc.get_cloud_configuration()
                if isinstance(cc, dict):
                    is_supervised = cc.get("IsSupervised", False)
        except Exception:
            pass
        
        # Check for passcode - if passcode set, erase requires passcode
        password_protected = vals.get("PasswordProtected", False)
        
        # Determine availability
        if activation_state in ["Unactivated", "ActivatedUnlocked"]:
            # Device is in Setup Assistant or unlocked - erase available
            return {
                "passed": True,
                "status": "AVAILABLE",
                "details": f"Activation state: {activation_state}, Supervised: {is_supervised}, Passcode: {password_protected}"
            }
        elif activation_state == "Activated":
            # Device is activated - erase available but requires passcode if set
            if password_protected:
                return {
                    "passed": True,
                    "status": "AVAILABLE_WITH_PASSCODE",
                    "details": f"Activation state: {activation_state}, Passcode required"
                }
            return {
                "passed": True,
                "status": "AVAILABLE",
                "details": f"Activation state: {activation_state}"
            }
        else:
            return {
                "passed": False,
                "status": "UNAVAILABLE",
                "details": f"Activation state: {activation_state} - device may be in recovery/DFU mode"
            }
    except Exception as e:
        return {
            "passed": False,
            "status": "ERROR",
            "details": f"Failed to check: {e}"
        }


async def check_setup_assistant_offline(udid: str) -> dict:
    """Step 2: Check if device can enter Setup Assistant offline (to Wi-Fi screen)."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        
        lockdown = await create_using_usbmux(serial=udid)
        vals = lockdown.all_values or {}
        
        activation_state = vals.get("ActivationState", "")
        
        # If already in Setup Assistant (Unactivated), we can proceed to Wi-Fi screen
        if activation_state == "Unactivated":
            return {
                "passed": True,
                "status": "IN_SETUP_ASSISTANT",
                "details": "Device is already in Setup Assistant (Unactivated state)"
            }
        
        # If activated, we need to check if we can erase and re-enter Setup Assistant
        # This is a manual step - user needs to erase and verify
        if activation_state == "Activated":
            return {
                "passed": True,
                "status": "REQUIRES_MANUAL_VERIFICATION",
                "details": "Device is activated. User must manually: 1) Erase All Content and Settings, 2) Verify Setup Assistant reaches Wi-Fi screen offline"
            }
        
        return {
            "passed": False,
            "status": "CANNOT_VERIFY",
            "details": f"Activation state: {activation_state} - cannot verify Setup Assistant entry"
        }
    except Exception as e:
        return {
            "passed": False,
            "status": "ERROR",
            "details": f"Failed to check: {e}"
        }


async def check_usb_pairing(udid: str) -> dict:
    """Step 3: Check USB pairing works normally."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        
        # Try to create lockdown connection
        lockdown = await create_using_usbmux(serial=udid)
        vals = lockdown.all_values or {}
        
        # If we got here, USB pairing works
        device_name = vals.get("DeviceName", "Unknown")
        product_type = vals.get("ProductType", "Unknown")
        
        return {
            "passed": True,
            "status": "PAIRED",
            "details": f"USB pairing working. Device: {device_name} ({product_type})"
        }
    except Exception as e:
        error_msg = str(e).lower()
        if "pair" in error_msg or "trust" in error_msg:
            return {
                "passed": False,
                "status": "NOT_PAIRED",
                "details": f"Device not paired/trusted: {e}"
            }
        return {
            "passed": False,
            "status": "ERROR",
            "details": f"USB connection failed: {e}"
        }


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
        async def operation(udid):
            step1 = await check_erase_availability(udid)
            step2 = await check_setup_assistant_offline(udid)
            step3 = await check_usb_pairing(udid)
            all_passed = all(r['passed'] for r in [step1, step2, step3])
            return {
                "steps": {
                    "erase_available": step1,
                    "setup_assistant_offline": step2,
                    "usb_pairing": step3,
                },
                "overall_passed": all_passed,
            }
        
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
        asyncio.run(cmd_detect(args))
    elif args.command == "list":
        asyncio.run(cmd_list_devices(args))
    elif args.command == "precheck":
        asyncio.run(cmd_precheck(args))
    elif args.command == "parse-backup":
        asyncio.run(cmd_parse_backup(args))
    elif args.command == "wipe":
        asyncio.run(cmd_wipe(args))
    elif args.command == "report":
        asyncio.run(cmd_report(args))
    elif args.command == "filter":
        asyncio.run(cmd_filter(args))
    elif args.command == "bulk":
        asyncio.run(cmd_bulk(args))
    elif args.command == "monitor":
        asyncio.run(cmd_monitor(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()