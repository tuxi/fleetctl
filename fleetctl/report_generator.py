"""
Report generation for fleetctl.
Generates PDF, JSON, and HTML reports for device management.
"""

from __future__ import annotations

import json
import csv
import io
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from abc import ABC, abstractmethod


@dataclass
class ReportConfig:
    """Configuration for report generation."""
    title: str = "Device Report"
    include_timestamp: bool = True
    include_errors: bool = True
    include_unavailable: bool = True
    company_name: Optional[str] = None
    logo_path: Optional[str] = None


class ReportGenerator(ABC):
    """Abstract base class for report generators."""
    
    @abstractmethod
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        """Generate report bytes."""
        pass
    
    @abstractmethod
    def get_extension(self) -> str:
        """Get file extension for this format."""
        pass


class JSONReportGenerator(ReportGenerator):
    """Generate JSON report with versioned schema."""
    
    SCHEMA_VERSION = "1.0"
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        report = {
            "schema_version": self.SCHEMA_VERSION,
            "metadata": {
                "title": config.title,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "device_count": len(devices),
                "company": config.company_name,
                "generator": "fleetctl",
            },
            "devices": devices,
        }
        return json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")
    
    def get_extension(self) -> str:
        return "json"
    
    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return JSON Schema for the report format."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "$id": "https://fleetctl.io/schemas/report/v1.0.json",
            "title": "fleetctl Device Fleet Report",
            "version": cls.SCHEMA_VERSION,
            "type": "object",
            "required": ["schema_version", "metadata", "devices"],
            "properties": {
                "schema_version": {
                    "type": "string",
                    "pattern": "^\\d+\\.\\d+$",
                    "description": "Schema version in MAJOR.MINOR format"
                },
                "metadata": {
                    "type": "object",
                    "required": ["title", "generated_at", "device_count", "generator"],
                    "properties": {
                        "title": {"type": "string"},
                        "generated_at": {"type": "string", "format": "date-time"},
                        "device_count": {"type": "integer", "minimum": 0},
                        "company": {"type": ["string", "null"]},
                        "generator": {"type": "string", "const": "fleetctl"}
                    }
                },
                "devices": {
                    "type": "array",
                    "items": {"$ref": "#/definitions/device"}
                }
            },
            "definitions": {
                "device": {
                    "type": "object",
                    "properties": {
                        "udid": {"type": "string"},
                        "identity": {"type": "object"},
                        "status": {"type": "object"},
                        "resources": {"type": "object"},
                        "metadata": {"type": "object"},
                        "errors": {"type": "object"},
                        "unavailable": {"type": "array", "items": {"type": "string"}},
                        "timestamp": {"type": "string", "format": "date-time"}
                    }
                }
            }
        }


class CSVReportGenerator(ReportGenerator):
    """Generate CSV report."""
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        if not devices:
            return b""
        
        # Flatten device data for CSV
        rows = []
        for device in devices:
            row = self._flatten_device(device)
            rows.append(row)
        
        if not rows:
            return b""
        
        output = io.StringIO()
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        
        return output.getvalue().encode("utf-8")
    
    def _flatten_device(self, device: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten nested device dict for CSV."""
        flat = {}
        
        def flatten(obj: Any, prefix: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    flatten(v, f"{prefix}{k}_")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    flatten(v, f"{prefix}{i}_")
            else:
                flat[prefix.rstrip("_")] = obj
        
        flatten(device)
        return flat
    
    def get_extension(self) -> str:
        return "csv"


class HTMLReportGenerator(ReportGenerator):
    """Generate HTML report with responsive design."""
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        html = self._generate_html(devices, config)
        return html.encode("utf-8")
    
    def _generate_html(self, devices: List[Dict[str, Any]], config: ReportConfig) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        report_version = "1.0"
        
        # Pre-compute summary stats
        total_devices = len(devices)
        supervised_count = sum(1 for d in devices if d.get('status', {}).get('is_supervised'))
        error_count = sum(1 for d in devices if d.get('errors'))
        passcode_count = sum(1 for d in devices if d.get('status', {}).get('password_protected'))
        unsupervised_count = sum(1 for d in devices if d.get('status', {}).get('is_supervised') is False)
        
        # Group devices by model for summary
        model_counts = {}
        ios_counts = {}
        chip_counts = {}
        for device in devices:
            model = device.get("product_type") or device.get("identity", {}).get("product_type") or "Unknown"
            ios = device.get("ios_version") or device.get("identity", {}).get("product_version") or "Unknown"
            chip = device.get("chip") or device.get("metadata", {}).get("chip") or "Unknown"
            model_counts[model] = model_counts.get(model, 0) + 1
            ios_counts[ios] = ios_counts.get(ios, 0) + 1
            chip_counts[chip] = chip_counts.get(chip, 0) + 1
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config.title}</title>
    <meta name="generator" content="fleetctl v{report_version}">
    <meta name="created" content="{timestamp}">
    <style>
        /* CSS Variables for theming */
        :root {{
            --primary: #007AFF;
            --primary-dark: #0056CC;
            --secondary: #5856D6;
            --success: #34C759;
            --warning: #FF9F0A;
            --error: #FF3B30;
            --bg-primary: #FFFFFF;
            --bg-secondary: #F5F5F7;
            --bg-tertiary: #E5E5EA;
            --text-primary: #1D1D1F;
            --text-secondary: #86868B;
            --border: #D2D2D7;
            --shadow: 0 2px 10px rgba(0,0,0,0.08);
            --shadow-hover: 0 4px 20px rgba(0,0,0,0.12);
            --radius: 12px;
            --radius-sm: 8px;
        }}
        
        /* Dark mode support */
        @media (prefers-color-scheme: dark) {{
            :root {{
                --primary: #0A84FF;
                --primary-dark: #0066E0;
                --bg-primary: #1C1C1E;
                --bg-secondary: #2C2C2E;
                --bg-tertiary: #3A3A3C;
                --text-primary: #FFFFFF;
                --text-secondary: #8E8E93;
                --border: #38383A;
            }}
        }}
        
        /* Print styles */
        @media print {{
            body {{ background: white; padding: 0; }}
            .container {{ box-shadow: none; border-radius: 0; max-width: 100%; }}
            .header {{ background: #007AFF !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .stat-card {{ background: #F5F5F7 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .devices-table th {{ background: #F5F5F7 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .status-badge {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
            .footer {{ display: none; }}
            .no-print {{ display: none; }}
            .device-detail {{ display: none; }}
            @page {{ margin: 1cm; size: A4; }}
        }}
        
        * {{ box-sizing: border-box; }}
        
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; 
            margin: 0; 
            padding: clamp(12px, 2vw, 24px); 
            background: var(--bg-secondary); 
            color: var(--text-primary);
            line-height: 1.5;
            font-size: clamp(13px, 0.9vw, 15px);
        }}
        
        .container {{ 
            max-width: 1400px; 
            margin: 0 auto; 
            background: var(--bg-primary); 
            border-radius: var(--radius); 
            box-shadow: var(--shadow); 
            overflow: hidden; 
        }}
        
        .header {{ 
            background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); 
            color: white; 
            padding: clamp(20px, 3vw, 36px); 
            position: relative;
            overflow: hidden;
        }}
        
        .header::before {{
            content: '';
            position: absolute;
            top: -50%;
            right: -10%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
            pointer-events: none;
        }}
        
        .header h1 {{ 
            margin: 0; 
            font-size: clamp(24px, 2.5vw, 32px); 
            font-weight: 600; 
            letter-spacing: -0.5px;
        }}
        
        .header .meta {{ 
            display: flex; 
            flex-wrap: wrap; 
            gap: clamp(12px, 1.5vw, 24px); 
            margin-top: clamp(12px, 1.5vw, 20px); 
            font-size: clamp(12px, 0.85vw, 14px); 
            opacity: 0.95; 
        }}
        
        .header .meta span {{
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(255,255,255,0.15);
            padding: 6px 12px;
            border-radius: 20px;
            backdrop-filter: blur(10px);
        }}
        
        .content {{ padding: clamp(20px, 2.5vw, 36px); }}
        
        /* Summary Grid */
        .summary {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(clamp(160px, 20vw, 220px), 1fr)); 
            gap: clamp(12px, 1.5vw, 20px); 
            margin-bottom: clamp(24px, 3vw, 36px); 
        }}
        
        .stat-card {{ 
            background: var(--bg-secondary); 
            border-radius: var(--radius-sm); 
            padding: clamp(16px, 2vw, 24px); 
            text-align: center; 
            border: 1px solid var(--border);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: var(--shadow-hover);
        }}
        
        .stat-value {{ 
            font-size: clamp(28px, 3.5vw, 40px); 
            font-weight: 700; 
            color: var(--text-primary); 
            line-height: 1.2;
        }}
        
        .stat-label {{ 
            font-size: clamp(11px, 0.8vw, 13px); 
            color: var(--text-secondary); 
            text-transform: uppercase; 
            letter-spacing: 0.8px; 
            margin-top: 6px; 
            font-weight: 500;
        }}
        
        .stat-card.primary .stat-value {{ color: var(--primary); }}
        .stat-card.success .stat-value {{ color: var(--success); }}
        .stat-card.warning .stat-value {{ color: var(--warning); }}
        .stat-card.error .stat-value {{ color: var(--error); }}
        
        /* Distribution Charts */
        .distribution {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); 
            gap: clamp(16px, 2vw, 24px); 
            margin-bottom: clamp(24px, 3vw, 36px); 
        }}
        
        .dist-card {{
            background: var(--bg-secondary);
            border-radius: var(--radius-sm);
            padding: clamp(16px, 2vw, 24px);
            border: 1px solid var(--border);
        }}
        
        .dist-title {{
            font-size: clamp(13px, 0.9vw, 15px);
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border);
        }}
        
        .dist-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid var(--border);
        }}
        
        .dist-item:last-child {{ border-bottom: none; }}
        
        .dist-label {{ 
            font-size: clamp(12px, 0.85vw, 14px); 
            color: var(--text-primary);
            max-width: 60%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        
        .dist-count {{ 
            font-size: clamp(12px, 0.85vw, 14px); 
            font-weight: 600; 
            color: var(--primary);
            background: rgba(0,122,255,0.1);
            padding: 4px 10px;
            border-radius: 20px;
            min-width: 50px;
            text-align: center;
        }}
        
        .dist-bar {{
            height: 6px;
            background: var(--bg-tertiary);
            border-radius: 3px;
            margin-top: 8px;
            overflow: hidden;
        }}
        
        .dist-bar-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--primary), var(--secondary));
            border-radius: 3px;
            transition: width 0.5s ease;
        }}
        
        /* Table Container with horizontal scroll on mobile */
        .table-container {{
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            border-radius: var(--radius-sm);
            border: 1px solid var(--border);
            margin-bottom: clamp(20px, 2.5vw, 30px);
        }}
        
        .devices-table {{ 
            width: 100%; 
            min-width: 800px;
            border-collapse: collapse; 
            font-size: clamp(12px, 0.85vw, 14px);
        }}
        
        .devices-table thead {{
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        
        .devices-table th {{ 
            text-align: left; 
            padding: clamp(10px, 1.2vw, 14px) clamp(12px, 1.5vw, 18px); 
            background: var(--bg-secondary); 
            font-weight: 600; 
            color: var(--text-primary); 
            border-bottom: 2px solid var(--border); 
            font-size: clamp(11px, 0.8vw, 13px); 
            text-transform: uppercase; 
            letter-spacing: 0.6px;
            white-space: nowrap;
        }}
        
        .devices-table td {{ 
            padding: clamp(10px, 1.2vw, 14px) clamp(12px, 1.5vw, 18px); 
            border-bottom: 1px solid var(--border); 
            color: var(--text-primary);
            vertical-align: middle;
        }}
        
        .devices-table tbody tr {{
            transition: background 0.15s ease;
        }}
        
        .devices-table tbody tr:hover td {{ 
            background: var(--bg-secondary); 
        }}
        
        .devices-table tbody tr:last-child td {{ border-bottom: none; }}
        
        /* Status Badges */
        .status-badge {{ 
            display: inline-flex; 
            align-items: center; 
            gap: 4px; 
            padding: 4px 10px; 
            border-radius: 100px; 
            font-size: clamp(11px, 0.8vw, 12px); 
            font-weight: 500; 
            white-space: nowrap;
        }}
        
        .status-badge::before {{
            content: '';
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: currentColor;
        }}
        
        .status-ok {{ background: rgba(52,199,89,0.15); color: var(--success); }}
        .status-warning {{ background: rgba(255,159,10,0.15); color: var(--warning); }}
        .status-error {{ background: rgba(255,59,48,0.15); color: var(--error); }}
        .status-unknown {{ background: rgba(134,134,139,0.15); color: var(--text-secondary); }}
        
        /* Device name cell */
        .device-name-cell {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        
        .device-name {{ 
            font-weight: 600; 
            color: var(--text-primary); 
        }}
        
        .device-udid {{ 
            font-size: clamp(10px, 0.75vw, 12px); 
            color: var(--text-secondary); 
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
        }}
        
        /* Expandable row indicator */
        .expand-indicator {{
            display: inline-flex;
            width: 20px;
            height: 20px;
            align-items: center;
            justify-content: center;
            color: var(--text-secondary);
            cursor: pointer;
            border-radius: 4px;
            transition: all 0.2s ease;
        }}
        
        .expand-indicator:hover {{
            background: var(--bg-tertiary);
            color: var(--primary);
        }}
        
        .expand-indicator.expanded {{
            transform: rotate(180deg);
        }}
        
        /* Detail row (hidden by default) */
        .detail-row {{
            display: none;
            background: var(--bg-secondary) !important;
        }}
        
        .detail-row.visible {{
            display: table-row;
            animation: slideDown 0.3s ease;
        }}
        
        @keyframes slideDown {{
            from {{ opacity: 0; transform: translateY(-10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        
        .detail-cell {{
            padding: 20px !important;
            background: var(--bg-secondary) !important;
        }}
        
        .detail-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }}
        
        .detail-item {{
            background: var(--bg-primary);
            padding: 12px 16px;
            border-radius: var(--radius-sm);
            border: 1px solid var(--border);
        }}
        
        .detail-label {{
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }}
        
        .detail-value {{
            font-size: 13px;
            font-weight: 500;
            color: var(--text-primary);
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', monospace;
        }}
        
        /* Footer */
        .footer {{ 
            padding: clamp(16px, 2vw, 24px) clamp(20px, 2.5vw, 36px); 
            background: var(--bg-secondary); 
            border-top: 1px solid var(--border); 
            font-size: clamp(11px, 0.8vw, 13px); 
            color: var(--text-secondary); 
            text-align: center; 
        }}
        
        .footer a {{
            color: var(--primary);
            text-decoration: none;
        }}
        
        .footer a:hover {{ text-decoration: underline; }}
        
        /* Empty state */
        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: var(--text-secondary);
        }}
        
        .empty-state svg {{
            width: 64px;
            height: 64px;
            margin-bottom: 16px;
            opacity: 0.5;
        }}
        
        /* Scrollbar styling */
        .table-container::-webkit-scrollbar {{
            height: 8px;
        }}
        
        .table-container::-webkit-scrollbar-track {{
            background: var(--bg-secondary);
        }}
        
        .table-container::-webkit-scrollbar-thumb {{
            background: var(--border);
            border-radius: 4px;
        }}
        
        .table-container::-webkit-scrollbar-thumb:hover {{
            background: var(--text-secondary);
        }}
        
        /* Reduced motion */
        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{
                animation-duration: 0.01ms !important;
                transition-duration: 0.01ms !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{config.title}</h1>
            <div class="meta">
                <span>📅 Generated: {timestamp}</span>
                <span>📱 Devices: {total_devices}</span>
                {f'<span>🏢 Company: {config.company_name}</span>' if config.company_name else ''}
                <span>📋 Version: {report_version}</span>
            </div>
        </div>
        <div class="content">
            <!-- Summary Cards -->
            <div class="summary">
                <div class="stat-card primary">
                    <div class="stat-value">{total_devices}</div>
                    <div class="stat-label">Total Devices</div>
                </div>
                <div class="stat-card success">
                    <div class="stat-value">{supervised_count}</div>
                    <div class="stat-label">Supervised</div>
                </div>
                <div class="stat-card warning">
                    <div class="stat-value">{unsupervised_count}</div>
                    <div class="stat-label">Unsupervised</div>
                </div>
                <div class="stat-card error">
                    <div class="stat-value">{error_count}</div>
                    <div class="stat-label">With Errors</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{passcode_count}</div>
                    <div class="stat-label">Passcode Protected</div>
                </div>
            </div>
            
            <!-- Distribution Charts -->
            <div class="distribution">
                <div class="dist-card">
                    <div class="dist-title">📱 By Model</div>
"""
        
        # Add model distribution
        max_model = max(model_counts.values()) if model_counts else 1
        for model, count in sorted(model_counts.items(), key=lambda x: -x[1]):
            pct = (count / max_model) * 100
            html += f"""
                    <div class="dist-item">
                        <span class="dist-label">{model}</span>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <span class="dist-count">{count}</span>
                            <div class="dist-bar" style="width: 100px;">
                                <div class="dist-bar-fill" style="width: {pct}%"></div>
                            </div>
                        </div>
                    </div>
"""
        
        html += """                </div>
                <div class="dist-card">
                    <div class="dist-title">🖥️ By iOS Version</div>
"""
        
        # Add iOS distribution
        max_ios = max(ios_counts.values()) if ios_counts else 1
        for ios, count in sorted(ios_counts.items(), key=lambda x: -x[1]):
            pct = (count / max_ios) * 100
            html += f"""
                    <div class="dist-item">
                        <span class="dist-label">iOS {ios}</span>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <span class="dist-count">{count}</span>
                            <div class="dist-bar" style="width: 100px;">
                                <div class="dist-bar-fill" style="width: {pct}%"></div>
                            </div>
                        </div>
                    </div>
"""
        
        html += """                </div>
                <div class="dist-card">
                    <div class="dist-title">🧠 By Chip</div>
"""
        
        # Add chip distribution
        max_chip = max(chip_counts.values()) if chip_counts else 1
        for chip, count in sorted(chip_counts.items(), key=lambda x: -x[1]):
            pct = (count / max_chip) * 100
            html += f"""
                    <div class="dist-item">
                        <span class="dist-label">{chip}</span>
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <span class="dist-count">{count}</span>
                            <div class="dist-bar" style="width: 100px;">
                                <div class="dist-bar-fill" style="width: {pct}%"></div>
                            </div>
                        </div>
                    </div>
"""
        
        html += """                </div>
            </div>
            
            <!-- Devices Table -->
            <div class="table-container">
                <table class="devices-table">
                    <thead>
                        <tr>
                            <th style="width: 40px;"></th>
                            <th>Device</th>
                            <th>Model</th>
                            <th>iOS</th>
                            <th>Chip</th>
                            <th>Supervised</th>
                            <th>Passcode</th>
                            <th>Storage</th>
                            <th>Battery</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        
        for idx, device in enumerate(devices):
            identity = device.get("identity", {})
            status = device.get("status", {})
            resources = device.get("resources", {})
            metadata = device.get("metadata", {})
            errors = device.get("errors", {})
            
            model = device.get("product_type") or device.get("identity", {}).get("product_type") or "Unknown"
            ios = device.get("ios_version") or device.get("identity", {}).get("product_version") or "Unknown"
            chip = device.get("chip") or device.get("metadata", {}).get("chip") or "Unknown"
            
            supervised = status.get("is_supervised")
            supervised_badge = "status-ok" if supervised else "status-unknown"
            supervised_text = "Yes" if supervised else ("No" if supervised is False else "Unknown")
            
            passcode = status.get("password_protected")
            passcode_badge = "status-ok" if passcode else ("status-warning" if passcode is False else "status-unknown")
            passcode_text = "Yes" if passcode else ("No" if passcode is False else "Unknown")
            
            storage = "Unknown"
            if device.get("resources", {}).get("total_data_capacity"):
                total = device["resources"]["total_data_capacity"]
                avail = device["resources"].get("data_available", 0)
                used = total - avail
                storage = f"{used / (1024**3):.1f} / {total / (1024**3):.1f} GB"
            
            battery = "Unknown"
            if device.get("resources", {}).get("battery_cycle_count") is not None:
                cycle = device["resources"]["battery_cycle_count"]
                design = device["resources"].get("battery_design_capacity", 0)
                full = device["resources"].get("battery_full_charge_capacity", 0)
                health = (full / design * 100) if design else 0
                battery = f"{cycle} cycles ({health:.0f}%)"
            
            has_errors = bool(device.get("errors"))
            status_badge = "status-error" if has_errors else "status-ok"
            status_text = "Errors" if has_errors else "OK"
            
            device_name = device.get('device_name') or device.get('identity', {}).get('device_name') or 'Unknown'
            udid = device.get('udid', '')
            
            # Build detail row content
            detail_html = self._build_detail_html(device, idx)
            
            html += f"""
                    <tr data-device-index="{idx}">
                        <td>
                            <button class="expand-indicator" onclick="toggleDetail({idx})" aria-label="Expand device details" title="Click to expand">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                            </button>
                        </td>
                        <td>
                            <div class="device-name-cell">
                                <span class="device-name">{device_name}</span>
                                <span class="device-udid">{udid[:8]}...</span>
                            </div>
                        </td>
                        <td>{model}</td>
                        <td>{ios}</td>
                        <td>{chip}</td>
                        <td><span class="status-badge {supervised_badge}">{supervised_text}</span></td>
                        <td><span class="status-badge {passcode_badge}">{passcode_text}</span></td>
                        <td>{storage}</td>
                        <td>{battery}</td>
                        <td><span class="status-badge {status_badge}">{status_text}</span></td>
                    </tr>
                    <tr class="detail-row" id="detail-{idx}">
                        <td colspan="11">
                            <div class="detail-cell">
                                {detail_html}
                            </div>
                        </tr>
"""
        
        html += """                    </tbody>
                </table>
            </div>
            
            <div class="footer">
                Generated by <strong>fleetctl</strong> • """ + timestamp + """ • 
                <a href="https://github.com/fleetctl/fleetctl" target="_blank" rel="noopener">Report Schema v""" + report_version + """</a>
            </div>
        </div>
    </div>
    
    <script>
        function toggleDetail(index) {{
            const row = document.getElementById('detail-' + index);
            const btn = row.previousElementSibling.querySelector('.expand-indicator');
            const isVisible = row.classList.contains('visible');
            
            if (isVisible) {{
                row.classList.remove('visible');
                btn.classList.remove('expanded');
            }} else {{
                row.classList.add('visible');
                btn.classList.add('expanded');
            }}
        }}
        
        // Keyboard support
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Enter' || e.key === ' ') {{
                const btn = e.target.closest('.expand-indicator');
                if (btn) {{
                    e.preventDefault();
                    btn.click();
                }}
            }}
        }});
        
        // Print: expand all rows
        window.addEventListener('beforeprint', () => {{
            document.querySelectorAll('.detail-row').forEach(row => row.classList.add('visible'));
            document.querySelectorAll('.expand-indicator').forEach(btn => btn.classList.add('expanded'));
        }});
    </script>
</body>
</html>"""
        return html
    
    def _build_detail_html(self, device: Dict[str, Any], index: int) -> str:
        """Build detailed device information for expandable row."""
        identity = device.get("identity", {})
        status = device.get("status", {})
        resources = device.get("resources", {})
        metadata = device.get("metadata", {})
        errors = device.get("errors", {})
        
        details = []
        
        # Identity section
        identity_fields = [
            ("UDID", device.get("udid")),
            ("Serial Number", identity.get("serial_number")),
            ("Device Name", identity.get("device_name") or device.get("device_name")),
            ("Product Type", identity.get("product_type") or device.get("product_type")),
            ("Product Version", identity.get("product_version") or device.get("product_version") or device.get("ios_version")),
            ("Build Version", identity.get("build_version")),
            ("Model Number", identity.get("model_number")),
            ("Hardware Model", identity.get("hardware_model")),
            ("Hardware Platform", identity.get("hardware_platform")),
            ("Activation State", identity.get("activation_state") or device.get("activation_state") or status.get("activation_state")),
            ("Region", identity.get("region_info")),
            ("IMEI", identity.get("imei")),
            ("MEID", identity.get("meid")),
            ("CPU Architecture", identity.get("cpu_architecture")),
            ("Device Class", identity.get("device_class")),
        ]
        
        for label, value in identity_fields:
            if value:
                details.append(("Identity", label, str(value)))
        
        # Status section
        status_fields = [
            ("Supervised", "Yes" if status.get("is_supervised") else ("No" if status.get("is_supervised") is False else "Unknown")),
            ("Passcode Protected", "Yes" if status.get("password_protected") else ("No" if status.get("password_protected") is False else "Unknown")),
            ("Configuration Source", str(status.get("configuration_source")) if status.get("configuration_source") is not None else "Unknown"),
            ("Cloud Config Present", "Yes" if status.get("cloud_configuration_present") else "No"),
            ("Profiles Count", str(status.get("profiles_count", 0))),
        ]
        
        for label, value in status_fields:
            if value and value != "Unknown":
                details.append(("Status", label, str(value)))
        
        # Resources section
        resource_fields = [
            ("Total Disk Capacity", self._format_bytes(resources.get("total_disk_capacity"))),
            ("Total Data Capacity", self._format_bytes(resources.get("total_data_capacity"))),
            ("Data Available", self._format_bytes(resources.get("data_available"))),
            ("System Capacity", self._format_bytes(resources.get("total_system_capacity"))),
            ("Battery Cycle Count", str(resources.get("battery_cycle_count")) if resources.get("battery_cycle_count") is not None else None),
            ("Battery Design Capacity", self._format_mah(resources.get("battery_design_capacity"))),
            ("Battery Full Charge Capacity", self._format_mah(resources.get("battery_full_charge_capacity"))),
            ("Apps Count", str(resources.get("apps_count")) if resources.get("apps_count") is not None else None),
            ("Apps Static Size", self._format_bytes(resources.get("apps_static_bytes"))),
            ("Apps Dynamic Size", self._format_bytes(resources.get("apps_dynamic_bytes"))),
        ]
        
        for label, value in resource_fields:
            if value:
                details.append(("Resources", label, str(value)))
        
        # Metadata section
        meta_fields = [
            ("Chip", metadata.get("chip") or device.get("chip")),
            ("iOS Version", metadata.get("ios_version") or device.get("ios_version")),
            ("Board ID", metadata.get("board_id") or device.get("board_id")),
            ("Hardware Platform", metadata.get("hardware_platform") or device.get("hardware_platform")),
        ]
        
        for label, value in meta_fields:
            if value:
                details.append(("Metadata", label, str(value)))
        
        # Profiles
        profiles = status.get("profiles", [])
        if profiles:
            for i, profile in enumerate(profiles):
                details.append(("Profiles", f"Profile {i+1}", profile.get("description") or profile.get("identifier", "Unknown")))
        
        # Errors
        if errors:
            for key, value in errors.items():
                details.append(("Errors", key, str(value)))
        
        # Unavailable fields
        unavailable = device.get("unavailable", [])
        if unavailable:
            for field in unavailable:
                details.append(("Unavailable", field, "Not accessible via public APIs"))
        
        # Build HTML
        if not details:
            return '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg><p>No detailed information available</p></div>'
        
        # Group by section
        sections = {}
        for section, label, value in details:
            if section not in sections:
                sections[section] = []
            sections[section].append((label, value))
        
        html_parts = []
        for section, items in sections.items():
            html_parts.append(f'<div class="detail-section"><h4 class="detail-section-title">{section}</h4><div class="detail-grid">')
            for label, value in items:
                html_parts.append(f'<div class="detail-item"><div class="detail-label">{label}</div><div class="detail-value">{value}</div></div>')
            html_parts.append('</div></div>')
        
        return ''.join(html_parts)
    
    def _format_bytes(self, bytes_val: Optional[int]) -> Optional[str]:
        if bytes_val is None:
            return None
        if bytes_val >= 1024**3:
            return f"{bytes_val / (1024**3):.2f} GB"
        elif bytes_val >= 1024**2:
            return f"{bytes_val / (1024**2):.2f} MB"
        elif bytes_val >= 1024:
            return f"{bytes_val / 1024:.2f} KB"
        return f"{bytes_val} bytes"
    
    def _format_mah(self, mah: Optional[int]) -> Optional[str]:
        if mah is None:
            return None
        return f"{mah} mAh"
    
    def get_extension(self) -> str:
        return "html"


class PDFReportGenerator(ReportGenerator):
    """Generate PDF report with professional formatting (watermark, TOC, page numbers, certificate layout)."""
    
    def __init__(self):
        self._pdf_available = False
        self._backend = None
        try:
            import weasyprint
            self._pdf_available = True
            self._backend = "weasyprint"
        except ImportError:
            try:
                import reportlab
                self._pdf_available = True
                self._backend = "reportlab"
            except ImportError:
                pass
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        if not self._pdf_available:
            raise RuntimeError("PDF generation requires weasyprint or reportlab. Install with: pip install weasyprint")
        
        # Use reportlab backend for better PDF features (watermark, page numbers, TOC)
        return self._generate_with_reportlab(devices, config)
    
    def _generate_with_weasyprint(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        """Generate PDF using weasyprint with professional styling."""
        import weasyprint
        
        # Generate enhanced HTML for PDF
        html_gen = HTMLReportGenerator()
        html_bytes = html_gen.generate(devices, config)
        html = html_bytes.decode("utf-8")
        
        # Add PDF-specific CSS
        pdf_css = """
        @page {
            size: A4;
            margin: 2cm 2cm 2.5cm 2cm;
            @top-center {
                content: "fleetctl Device Fleet Report";
                font-size: 10px;
                color: #666;
            }
            @bottom-center {
                content: "Page " counter(page) " of " counter(pages);
                font-size: 10px;
                color: #666;
            }
            @bottom-right {
                content: "Confidential - fleetctl";
                font-size: 8px;
                color: #999;
            }
        }
        
        /* Watermark */
        body::before {
            content: "fleetctl";
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%) rotate(-45deg);
            font-size: 120px;
            color: rgba(0, 122, 255, 0.03);
            z-index: -1;
            pointer-events: none;
            white-space: nowrap;
            font-weight: 700;
            letter-spacing: 20px;
        }
        
        /* Hide interactive elements in PDF */
        .expand-indicator, .no-print { display: none !important; }
        .detail-row { display: none !important; }
        
        /* Ensure tables don't break awkwardly */
        .devices-table { page-break-inside: auto; }
        .devices-table tr { page-break-inside: avoid; page-break-after: auto; }
        .stat-card { page-break-inside: avoid; }
        .dist-card { page-break-inside: avoid; }
        
        /* TOC styling */
        .toc { page-break-after: always; }
        .toc h2 { border-bottom: 2px solid var(--primary); padding-bottom: 8px; }
        .toc ul { list-style: none; padding: 0; }
        .toc li { padding: 8px 0; border-bottom: 1px dotted var(--border); }
        .toc a { text-decoration: none; color: var(--text-primary); }
        .toc a:hover { color: var(--primary); }
        """
        
        # Inject PDF-specific CSS into HTML
        html = html.replace("</head>", f"<style>{pdf_css}</style></head>")
        
        # Add TOC after header
        toc_html = self._generate_toc(devices, config)
        html = html.replace('<div class="content">', f'<div class="content">{toc_html}')
        
        pdf = weasyprint.HTML(string=html).write_pdf(
            stylesheets=[weasyprint.CSS(string=pdf_css)]
        )
        return pdf
    
    def _generate_toc(self, devices: List[Dict[str, Any]], config: ReportConfig) -> str:
        """Generate table of contents."""
        toc = ['<div class="toc no-print"><h2>Table of Contents</h2><ul>']
        toc.append(f'<li><a href="#summary">Executive Summary</a></li>')
        toc.append(f'<li><a href="#distribution">Device Distribution</a></li>')
        toc.append(f'<li><a href="#devices">Device Inventory ({len(devices)} devices)</a></li>')
        
        # Add device anchors
        for i, device in enumerate(devices):
            name = device.get('device_name') or device.get('identity', {}).get('device_name') or f'Device {i+1}'
            udid = device.get('udid', '')[:8]
            toc.append(f'<li><a href="#device-{i}">{name} ({udid}...)</a></li>')
        
        toc.append('</ul></div>')
        return ''.join(toc)
    
    def _generate_with_reportlab(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        """Fallback PDF generation with reportlab - enhanced with page numbers, watermark, TOC."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            PageBreak, KeepTogether, Frame, PageTemplate, BaseDocTemplate
        )
        from reportlab.lib import colors
        from reportlab.lib.units import inch, cm
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        import io
        
        buffer = io.BytesIO()
        
        # Custom doc template with page numbers and watermark
        class NumberedDocTemplate(BaseDocTemplate):
            def __init__(self, filename, **kwargs):
                super().__init__(filename, **kwargs)
                self.page_count = 0
            
            def afterPage(self):
                self.page_count += 1
                super().afterPage()
        
        doc = NumberedDocTemplate(buffer, pagesize=A4,
            leftMargin=2*cm, rightMargin=2*cm,
            topMargin=2*cm, bottomMargin=2.5*cm)
        
        # Define page template with header/footer
        frame = Frame(doc.leftMargin, doc.bottomMargin,
                     doc.width, doc.height, id='normal')
        
        def add_page_number(canvas, doc):
            canvas.saveState()
            # Watermark
            canvas.setFont('Helvetica-Bold', 80)
            canvas.setFillColorRGB(0, 0.48, 1, alpha=0.02)
            canvas.translate(A4[0]/2, A4[1]/2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "fleetctl")
            canvas.rotate(-45)
            canvas.translate(-A4[0]/2, -A4[1]/2)
            
            # Page number
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(colors.grey)
            page_num = canvas.getPageNumber()
            text = f"Page {page_num}"
            canvas.drawCentredString(A4[0]/2, 1.5*cm, text)
            
            # Footer
            canvas.setFont('Helvetica', 7)
            canvas.drawString(2*cm, 1.5*cm, "fleetctl Device Fleet Report - Confidential")
            canvas.drawRightString(A4[0] - 2*cm, 1.5*cm, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d')}")
            canvas.restoreState()
        
        template = PageTemplate(id='main', frames=[frame], onPage=add_page_number)
        doc.addPageTemplates([template])
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle('CustomTitle', parent=styles['Title'],
                                    fontSize=24, textColor=colors.HexColor('#007AFF'),
                                    spaceAfter=6, alignment=TA_CENTER)
        subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'],
                                       fontSize=10, textColor=colors.grey,
                                       spaceAfter=20, alignment=TA_CENTER)
        heading_style = ParagraphStyle('Heading2', parent=styles['Heading2'],
                                      fontSize=14, textColor=colors.HexColor('#007AFF'),
                                      spaceBefore=16, spaceAfter=8,
                                      borderWidth=1, borderPadding=0,
                                      borderColor=colors.HexColor('#007AFF'))
        toc_style = ParagraphStyle('TOC', parent=styles['Normal'],
                                  fontSize=10, leading=14,
                                  leftIndent=20, spaceAfter=4)
        
        story = []
        
        # Cover page
        story.append(Spacer(1, 5*cm))
        story.append(Paragraph(config.title, title_style))
        story.append(Spacer(1, 1*cm))
        story.append(Paragraph(f"Device Fleet Report", subtitle_style))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", subtitle_style))
        story.append(Paragraph(f"Total Devices: {len(devices)}", subtitle_style))
        if config.company_name:
            story.append(Paragraph(f"Company: {config.company_name}", subtitle_style))
        story.append(PageBreak())
        
        # Table of Contents
        story.append(Paragraph("Table of Contents", styles['Heading1']))
        story.append(Spacer(1, 12))
        toc_items = [
            ("1.", "Executive Summary"),
            ("2.", "Device Distribution"),
            ("3.", f"Device Inventory ({len(devices)} devices)"),
        ]
        for i, device in enumerate(devices):
            name = device.get('device_name') or device.get('identity', {}).get('device_name') or f'Device {i+1}'
            udid = device.get('udid', '')[:8]
            toc_items.append((f"3.{i+1}", f"{name} ({udid}...)"))
        
        for num, title in toc_items:
            story.append(Paragraph(f'{num} {title}', toc_style))
        story.append(PageBreak())
        
        # Executive Summary
        story.append(Paragraph("Executive Summary", styles['Heading1']))
        story.append(Spacer(1, 12))
        
        total_devices = len(devices)
        supervised_count = sum(1 for d in devices if d.get('status', {}).get('is_supervised'))
        error_count = sum(1 for d in devices if d.get('errors'))
        passcode_count = sum(1 for d in devices if d.get('status', {}).get('password_protected'))
        unsupervised_count = sum(1 for d in devices if d.get('status', {}).get('is_supervised') is False)
        
        summary_data = [
            ["Metric", "Value"],
            ["Total Devices", str(total_devices)],
            ["Supervised", str(supervised_count)],
            ["Unsupervised", str(unsupervised_count)],
            ["With Errors", str(error_count)],
            ["Passcode Protected", str(passcode_count)],
        ]
        
        table = Table(summary_data, colWidths=[8*cm, 8*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007AFF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F7')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D2D2D7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F7')]),
        ]))
        story.append(table)
        story.append(PageBreak())
        
        # Device Distribution
        story.append(Paragraph("Device Distribution", styles['Heading1']))
        story.append(Spacer(1, 12))
        
        # Model distribution
        model_counts = {}
        ios_counts = {}
        chip_counts = {}
        for device in devices:
            model = device.get("product_type") or device.get("identity", {}).get("product_type") or "Unknown"
            ios = device.get("ios_version") or device.get("identity", {}).get("product_version") or "Unknown"
            chip = device.get("chip") or device.get("metadata", {}).get("chip") or "Unknown"
            model_counts[model] = model_counts.get(model, 0) + 1
            ios_counts[ios] = ios_counts.get(ios, 0) + 1
            chip_counts[chip] = chip_counts.get(chip, 0) + 1
        
        for title, counts in [("By Model", model_counts), ("By iOS Version", ios_counts), ("By Chip", chip_counts)]:
            story.append(Paragraph(title, styles['Heading2']))
            story.append(Spacer(1, 6))
            dist_data = [["Category", "Count", "Percentage"]]
            total = sum(counts.values()) or 1
            for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
                dist_data.append([cat, str(count), f"{count/total*100:.1f}%"])
            dist_table = Table(dist_data, colWidths=[6*cm, 3*cm, 3*cm])
            dist_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007AFF')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F7')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D2D2D7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F7')]),
            ]))
            story.append(dist_table)
            story.append(Spacer(1, 12))
        story.append(PageBreak())
        
        # Device Inventory
        story.append(Paragraph("Device Inventory", styles['Heading1']))
        story.append(Spacer(1, 12))
        
        device_data = [["Device", "Model", "iOS", "Chip", "Supervised", "Passcode", "Status"]]
        for device in devices:
            identity = device.get("identity", {})
            status = device.get("status", {})
            metadata = device.get("metadata", {})
            
            model = device.get("product_type") or device.get("identity", {}).get("product_type") or "Unknown"
            ios = device.get("ios_version") or device.get("identity", {}).get("product_version") or "Unknown"
            chip = device.get("chip") or device.get("metadata", {}).get("chip") or "Unknown"
            
            supervised = "Yes" if status.get("is_supervised") else ("No" if status.get("is_supervised") is False else "Unknown")
            passcode = "Yes" if status.get("password_protected") else ("No" if status.get("password_protected") is False else "Unknown")
            has_errors = bool(device.get("errors"))
            status_text = "Errors" if has_errors else "OK"
            
            device_data.append([
                device.get("device_name") or device.get("identity", {}).get("device_name") or "Unknown",
                model, ios, chip, supervised, passcode, status_text
            ])
        
        device_table = Table(device_data, colWidths=[2.5*cm, 2*cm, 1.5*cm, 1.5*cm, 2*cm, 2*cm, 2*cm])
        device_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007AFF')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F7')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D2D2D7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F7')]),
        ]))
        story.append(device_table)
        
        doc.build(story)
        return buffer.getvalue()
    
    def get_extension(self) -> str:
        return "pdf"


class ReportGeneratorFactory:
    """Factory for creating report generators."""
    
    _generators = {
        "json": JSONReportGenerator,
        "csv": CSVReportGenerator,
        "html": HTMLReportGenerator,
        "pdf": PDFReportGenerator,
    }
    
    @classmethod
    def create(cls, format: str) -> ReportGenerator:
        if format not in cls._generators:
            raise ValueError(f"Unsupported format: {format}. Supported: {list(cls._generators.keys())}")
        return cls._generators[format]()
    
    @classmethod
    def generate_report(
        cls,
        devices: List[Dict[str, Any]],
        format: str,
        config: Optional[ReportConfig] = None,
        output_path: Optional[Path] = None
    ) -> bytes:
        """Generate report in specified format."""
        config = config or ReportConfig()
        generator = cls.create(format)
        content = generator.generate(devices, config)
        
        if output_path:
            output_path.write_bytes(content)
        
        return content
    
    @classmethod
    def get_supported_formats(cls) -> List[str]:
        return list(cls._generators.keys())


def generate_device_report(
    devices: List[Dict[str, Any]],
    format: str = "html",
    title: str = "Device Fleet Report",
    company_name: Optional[str] = None,
    output_path: Optional[Path] = None
) -> bytes:
    """Convenience function to generate device report."""
    config = ReportConfig(title=title, company_name=company_name)
    return ReportGeneratorFactory.generate_report(devices, format, config, output_path)