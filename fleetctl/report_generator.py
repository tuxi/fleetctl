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
    """Generate JSON report."""
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        report = {
            "metadata": {
                "title": config.title,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "device_count": len(devices),
                "company": config.company_name,
            },
            "devices": devices,
        }
        return json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")
    
    def get_extension(self) -> str:
        return "json"


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
    """Generate HTML report."""
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        html = self._generate_html(devices, config)
        return html.encode("utf-8")
    
    def _generate_html(self, devices: List[Dict[str, Any]], config: ReportConfig) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config.title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: #f5f5f7; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }}
        .header {{ background: linear-gradient(135deg, #007AFF 0%, #5856D6 100%); color: white; padding: 30px; }}
        .header h1 {{ margin: 0; font-size: 28px; font-weight: 600; }}
        .header p {{ margin: 8px 0 0; opacity: 0.9; }}
        .meta {{ display: flex; gap: 20px; margin-top: 16px; font-size: 14px; opacity: 0.9; }}
        .content {{ padding: 30px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }}
        .stat-card {{ background: #f5f5f7; border-radius: 8px; padding: 20px; text-align: center; }}
        .stat-value {{ font-size: 32px; font-weight: 600; color: #1d1d1f; }}
        .stat-label {{ font-size: 13px; color: #86868b; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
        .devices-table {{ width: 100%; border-collapse: collapse; }}
        .devices-table th {{ text-align: left; padding: 12px 16px; background: #f5f5f7; font-weight: 600; color: #1d1d1f; border-bottom: 1px solid #d2d2d7; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; }}
        .devices-table td {{ padding: 12px 16px; border-bottom: 1px solid #e5e5ea; font-size: 14px; color: #1d1d1f; }}
        .devices-table tr:hover td {{ background: #f5f5f7; }}
        .status-badge {{ display: inline-block; padding: 4px 10px; border-radius: 100px; font-size: 12px; font-weight: 500; }}
        .status-ok {{ background: #E8F5E9; color: #2E7D32; }}
        .status-warning {{ background: #FFF3E0; color: #E65100; }}
        .status-error {{ background: #FBE9E7; color: #C62828; }}
        .status-unknown {{ background: #ECEFF1; color: #455A64; }}
        .error {{ color: #C62828; font-size: 12px; }}
        .footer {{ padding: 20px 30px; background: #f5f5f7; border-top: 1px solid #e5e5ea; font-size: 12px; color: #86868b; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{config.title}</h1>
            <div class="meta">
                <span>Generated: {timestamp}</span>
                <span>Devices: {len(devices)}</span>
                {f'<span>Company: {config.company_name}</span>' if config.company_name else ''}
            </div>
        </div>
        <div class="content">
            <div class="summary">
                <div class="stat-card">
                    <div class="stat-value">{len(devices)}</div>
                    <div class="stat-label">Total Devices</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{sum(1 for d in devices if d.get('status', {}).get('is_supervised'))}</div>
                    <div class="stat-label">Supervised</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{sum(1 for d in devices if d.get('errors'))}</div>
                    <div class="stat-label">With Errors</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{sum(1 for d in devices if d.get('status', {}).get('password_protected'))}</div>
                    <div class="stat-label">Passcode Protected</div>
                </div>
            </div>
            
            <table class="devices-table">
                <thead>
                    <tr>
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
        
        for device in devices:
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
            
            html += f"""
                    <tr>
                        <td><strong>{device.get('device_name') or device.get('identity', {}).get('device_name') or 'Unknown'}</strong><br><small>{device.get('udid', '')[:8]}...</small></td>
                        <td>{model}</td>
                        <td>{ios}</td>
                        <td>{chip}</td>
                        <td><span class="status-badge {supervised_badge}">{supervised_text}</span></td>
                        <td><span class="status-badge {passcode_badge}">{passcode_text}</span></td>
                        <td>{storage}</td>
                        <td>{battery}</td>
                        <td><span class="status-badge {status_badge}">{status_text}</span></td>
                    </tr>
"""
        
        html += """                </tbody>
            </table>
        </div>
        <div class="footer">
            Generated by fleetctl • """ + timestamp + """
        </div>
    </div>
</body>
</html>"""
        return html
    
    def get_extension(self) -> str:
        return "html"


class PDFReportGenerator(ReportGenerator):
    """Generate PDF report (requires weasyprint or reportlab)."""
    
    def __init__(self):
        self._pdf_available = False
        try:
            import weasyprint
            self._pdf_available = True
        except ImportError:
            try:
                import reportlab
                self._pdf_available = True
            except ImportError:
                pass
    
    def generate(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        if not self._pdf_available:
            raise RuntimeError("PDF generation requires weasyprint or reportlab. Install with: pip install weasyprint")
        
        # Generate HTML first, then convert to PDF
        html_gen = HTMLReportGenerator()
        html = html_gen.generate(devices, config)
        
        try:
            import weasyprint
            pdf = weasyprint.HTML(string=html.decode("utf-8")).write_pdf()
            return pdf
        except ImportError:
            # Fallback to reportlab
            return self._generate_with_reportlab(devices, config)
    
    def _generate_with_reportlab(self, devices: List[Dict[str, Any]], config: ReportConfig) -> bytes:
        """Fallback PDF generation with reportlab."""
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.units import inch
        import io
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        story.append(Paragraph(config.title, styles['Title']))
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}", styles['Normal']))
        story.append(Paragraph(f"Devices: {len(devices)}", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Summary table
        summary_data = [
            ["Metric", "Value"],
            ["Total Devices", str(len(devices))],
            ["Supervised", str(sum(1 for d in devices if d.get('status', {}).get('is_supervised')))],
            ["With Errors", str(sum(1 for d in devices if d.get('errors')))],
            ["Passcode Protected", str(sum(1 for d in devices if d.get('status', {}).get('password_protected')))],
        ]
        
        table = Table(summary_data, colWidths=[2*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Device table
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
        
        device_table = Table(device_data, colWidths=[1.2*inch, 1*inch, 0.7*inch, 0.7*inch, 0.8*inch, 0.8*inch, 0.8*inch])
        device_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
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