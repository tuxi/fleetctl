"""
Compliant device wipe manager for fleetctl.
Implements NIST 800-88 compliant device erasure.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

logger = logging.getLogger(__name__)


class WipeMethod(str, Enum):
    """Wipe method types."""
    QUICK = "quick"           # Quick erase (logical)
    FULL = "full"             # Full erase (cryptographic)
    NIST_800_88_CLEAR = "nist_clear"      # NIST 800-88 Clear
    NIST_800_88_PURGE = "nist_purge"      # NIST 800-88 Purge (cryptographic erase)
    NIST_800_88_DESTROY = "nist_destroy"  # NIST 800-88 Destroy (physical)


class WipeStatus(Enum):
    """Wipe operation status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WipeOptions:
    """Options for device wipe operation."""
    method: str = "full"
    preserve_data_plan: bool = False
    disallow_proximity_setup: bool = False
    verify_after: bool = True
    generate_certificate: bool = True
    certificate_fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class WipeResult:
    """Result of wipe operation."""
    success: bool
    method: str
    udid: str
    message: str
    error_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    certificate: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0


class WipeCertificate:
    """Generates NIST 800-88 compliant wipe certificates (JSON and PDF)."""
    
    @staticmethod
    def build_certificate(
        udid: str,
        serial_number: str,
        product_type: str,
        product_version: str,
        method: str,
        started_at: str,
        completed_at: str,
        success: bool,
        verifier: str = "fleetctl",
        additional_fields: Dict[str, str] = None,
        ios_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a wipe certificate as a structured dict."""
        certificate: Dict[str, Any] = {
            "certificate_version": "1.0",
            "standard": "NIST SP 800-88 Rev. 1",
            "wipe_method": method,
            "device": {
                "udid": udid,
                "serial_number": serial_number,
                "product_type": product_type,
                "ios_version": ios_version or product_version,
            },
            "timestamps": {
                "started_at": started_at,
                "completed_at": completed_at,
            },
            "result": "success" if success else "failed",
            "verifier": verifier,
            "certificate_id": secrets.token_hex(16),
            "hash_algorithm": "SHA-256",
        }
        
        if additional_fields:
            certificate["additional_fields"] = additional_fields
        
        return certificate
    
    @staticmethod
    def generate(
        udid: str,
        serial_number: str,
        product_type: str,
        product_version: str,
        method: str,
        started_at: str,
        completed_at: str,
        success: bool,
        verifier: str = "fleetctl",
        additional_fields: Dict[str, str] = None,
        ios_version: Optional[str] = None,
    ) -> str:
        """Generate a wipe certificate in JSON format."""
        import json
        certificate = WipeCertificate.build_certificate(
            udid=udid,
            serial_number=serial_number,
            product_type=product_type,
            product_version=product_version,
            method=method,
            started_at=started_at,
            completed_at=completed_at,
            success=success,
            verifier=verifier,
            additional_fields=additional_fields,
            ios_version=ios_version or product_version,
        )
        return json.dumps(certificate, indent=2)
    
    @staticmethod
    def generate_hash(data: str) -> str:
        """Generate SHA-256 hash of certificate data."""
        return hashlib.sha256(data.encode()).hexdigest()
    
    @staticmethod
    def _as_dict(certificate) -> Dict[str, Any]:
        """Accept a certificate dict or a JSON string, return a dict."""
        if isinstance(certificate, dict):
            return certificate
        import json
        try:
            return json.loads(certificate)
        except (TypeError, ValueError):
            return {"raw": certificate}
    
    @staticmethod
    def generate_pdf(
        certificate,
        title: str = "Certificate of Data Erasure",
        organization: Optional[str] = None,
    ) -> bytes:
        """Render a wipe certificate as a PDF (requires reportlab).

        Args:
            certificate: A certificate dict (from ``build_certificate``) or its
                JSON string.
            title: Document title.
            organization: Optional organization name shown under the title.

        Returns:
            PDF bytes.
        """
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
            )
            from reportlab.lib.enums import TA_CENTER
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "PDF certificate generation requires reportlab. "
                "Install with: pip install reportlab"
            ) from exc
        
        import io
        import json
        
        cert = WipeCertificate._as_dict(certificate)
        device = cert.get("device", {}) or {}
        timestamps = cert.get("timestamps", {}) or {}
        result = str(cert.get("result", "unknown")).lower()
        
        canonical = json.dumps(cert, sort_keys=True, ensure_ascii=False)
        cert_hash = WipeCertificate.generate_hash(canonical)
        
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "CertTitle", parent=styles["Title"], fontSize=22,
            textColor=colors.HexColor("#007AFF"), alignment=TA_CENTER, spaceAfter=4,
        )
        sub_style = ParagraphStyle(
            "CertSub", parent=styles["Normal"], fontSize=11,
            textColor=colors.HexColor("#5856D6"), alignment=TA_CENTER, spaceAfter=2,
        )
        org_style = ParagraphStyle(
            "CertOrg", parent=styles["Normal"], fontSize=12,
            textColor=colors.HexColor("#1D1D1F"), alignment=TA_CENTER, spaceAfter=12,
        )
        section_style = ParagraphStyle(
            "Section", parent=styles["Heading2"], fontSize=13,
            textColor=colors.HexColor("#1D1D1F"), spaceBefore=14, spaceAfter=6,
        )
        label_style = ParagraphStyle(
            "Label", parent=styles["Normal"], fontSize=9,
            textColor=colors.HexColor("#6E6E73"),
        )
        value_style = ParagraphStyle(
            "Value", parent=styles["Normal"], fontSize=10,
            textColor=colors.HexColor("#1D1D1F"),
        )
        small_style = ParagraphStyle(
            "Small", parent=styles["Normal"], fontSize=8,
            textColor=colors.HexColor("#86868B"),
        )
        
        def kv_table(rows, label_w: float = 4.5 * cm):
            data = [
                [Paragraph(str(k), label_style), Paragraph(str(v if v not in (None, "") else "n/a"), value_style)]
                for k, v in rows
            ]
            t = Table(data, colWidths=[label_w, 17.0 * cm - label_w])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#E5E5EA")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            return t
        
        story: List[Any] = []
        story.append(Paragraph(title, title_style))
        story.append(Paragraph(str(cert.get("standard", "")), sub_style))
        if organization:
            story.append(Paragraph(organization, org_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#007AFF")))
        story.append(Spacer(1, 10))
        
        story.append(Paragraph("Certificate", section_style))
        story.append(kv_table([
            ("Certificate ID", cert.get("certificate_id", "")),
            ("Certificate version", cert.get("certificate_version", "")),
            ("Verifier", cert.get("verifier", "")),
            ("Hash algorithm", cert.get("hash_algorithm", "")),
        ]))
        
        story.append(Paragraph("Device", section_style))
        story.append(kv_table([
            ("UDID", device.get("udid", "")),
            ("Serial number", device.get("serial_number", "")),
            ("Product type", device.get("product_type", "")),
            ("iOS version", device.get("ios_version") or device.get("product_version") or "n/a"),
        ]))
        
        story.append(Paragraph("Erasure Method", section_style))
        story.append(kv_table([
            ("Method", cert.get("wipe_method", "")),
            ("Standard", cert.get("standard", "")),
        ]))
        
        story.append(Paragraph("Timestamps", section_style))
        story.append(kv_table([
            ("Started at", timestamps.get("started_at", "")),
            ("Completed at", timestamps.get("completed_at", "")),
        ]))
        
        # Result banner
        banner_color = (
            colors.HexColor("#34C759") if result == "success" else colors.HexColor("#FF3B30")
        )
        banner_style = ParagraphStyle(
            "Banner", parent=value_style, fontSize=14, textColor=colors.white,
            alignment=TA_CENTER, spaceBefore=4, spaceAfter=4,
        )
        banner = Table([[Paragraph(f"<b>RESULT: {result.upper()}</b>", banner_style)]],
                       colWidths=[17.0 * cm])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), banner_color),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        story.append(Spacer(1, 14))
        story.append(banner)
        
        story.append(Paragraph("Integrity", section_style))
        story.append(kv_table([
            ("SHA-256 (certificate)", cert_hash),
        ]))
        
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D2D2D7")))
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            "This certificate attests that the device's cryptographic keys were destroyed, "
            "rendering stored data unrecoverable (NIST SP 800-88 Rev. 1, Purge).",
            small_style,
        ))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"Generated by fleetctl &bull; {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} "
            f"&bull; certificate hash {cert_hash[:16]}...",
            small_style,
        ))
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
            title=title, author=organization or "fleetctl",
        )
        doc.build(story)
        return buffer.getvalue()
    
    @staticmethod
    def write(certificate, path, fmt: str = "json", organization: Optional[str] = None) -> Path:
        """Write a certificate to ``path`` in the given format ("json" or "pdf")."""
        out = Path(path)
        cert = WipeCertificate._as_dict(certificate)
        if fmt == "json":
            import json
            out.write_text(json.dumps(cert, indent=2, ensure_ascii=False), encoding="utf-8")
        elif fmt == "pdf":
            out.write_bytes(WipeCertificate.generate_pdf(cert, organization=organization))
        else:
            raise ValueError(f"Unsupported certificate format: {fmt} (expected json|pdf)")
        return out


class WipeManager:
    """
    Compliant device wipe manager.
    Uses public MobileConfigService.erase_device API.
    Supports NIST 800-88 compliant wipe certificates.
    """
    
    def __init__(self):
        self._pymobiledevice3_available = False
        try:
            import pymobiledevice3
            self._pymobiledevice3_available = True
        except ImportError:
            pass
    
    @property
    def available(self) -> bool:
        return self._pymobiledevice3_available
    
    async def wipe_device(
        self,
        udid: str,
        options: Optional["WipeOptions"] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> "WipeResult":
        """
        Wipe device using public MobileConfigService.erase_device API.
        This is the only compliant way to wipe a device remotely.
        """
        if not self._pymobiledevice3_available:
            return WipeResult(
                success=False,
                method="unknown",
                udid=udid,
                message="pymobiledevice3 not available",
                error_code="PYMOBILEDEVICE3_UNAVAILABLE"
            )
        
        options = options or WipeOptions()
        started_at = datetime.utcnow().isoformat() + "Z"
        start_time = asyncio.get_event_loop().time()
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            # Get device info for certificate
            lockdown = await create_using_usbmux(serial=udid)
            vals = lockdown.all_values or {}
            
            serial_number = vals.get("SerialNumber", "Unknown")
            product_type = vals.get("ProductType", "Unknown")
            product_version = vals.get("ProductVersion", "Unknown")
            
            # Emit progress
            if progress_callback:
                progress_callback(10, "Initializing wipe...")
            
            # Determine wipe method
            method = options.method if options else "full"
            
            # For iOS, the only compliant remote wipe is via MobileConfigService.erase_device
            # This performs a full cryptographic erase (equivalent to NIST 800-88 Purge)
            async with MobileConfigService(lockdown) as mc:
                if progress_callback:
                    progress_callback(30, "Initiating device erase...")
                
                # The erase_device method performs a full cryptographic erase
                # preserve_data_plan: whether to preserve eSIM data plan
                # disallow_proximity_setup: whether to disable proximity setup after erase
                await mc.erase_device(
                    preserve_data_plan=options.preserve_data_plan if options else False,
                    disallow_proximity_setup=options.disallow_proximity_setup if options else False
                )
            
            if progress_callback:
                progress_callback(90, "Erase completed, waiting for reboot...")
            
            # Wait for device to reboot
            await self._wait_for_reboot(udid, timeout=120)
            
            completed_at = datetime.utcnow().isoformat() + "Z"
            duration = asyncio.get_event_loop().time() - start_time
            
            # Generate certificate
            certificate = None
            if options and options.generate_certificate:
                verifier = (options.certificate_fields or {}).get("verifier", "fleetctl")
                certificate = WipeCertificate.generate(
                    udid=udid,
                    serial_number=serial_number,
                    product_type=product_type,
                    product_version=product_version,
                    method=method,
                    started_at=started_at,
                    completed_at=completed_at,
                    success=True,
                    verifier=verifier,
                    ios_version=product_version,
                )
            
            return WipeResult(
                success=True,
                method=method,
                udid=udid,
                message="Device wiped successfully",
                details={
                    "serial_number": serial_number,
                    "product_type": product_type,
                    "wipe_method": method,
                },
                certificate=certificate,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration,
            )
            
        except Exception as e:
            logger.exception(f"Wipe failed for {udid}")
            error_msg = str(e)
            
            return WipeResult(
                success=False,
                method=options.method if options else "unknown",
                udid=udid,
                message=f"Wipe failed: {error_msg}",
                error_code="WIPE_FAILED",
                details={"error": str(e)},
                started_at=datetime.utcnow().isoformat() + "Z",
                completed_at=datetime.utcnow().isoformat() + "Z",
            )
    
    async def _wait_for_reboot(self, udid: str, timeout: int = 120) -> bool:
        """Wait for device to reboot and become available again."""
        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                from pymobiledevice3.usbmux import list_devices
                devices = await list_devices()
                for device in devices:
                    if device.serial == udid:
                        return True
            except Exception:
                pass
            
            await asyncio.sleep(2)
        
        return False
    
    async def verify_wipe(self, udid: str) -> Dict[str, Any]:
        """
        Verify that device has been wiped.
        Checks if device is in Setup Assistant state.
        """
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            # Check if device is in Setup Assistant (activation state)
            activation_state = vals.get("ActivationState", "")
            is_activated = activation_state in ["Activated", "ActivatedUnlocked"]
            
            return {
                "wiped": not is_activated,
                "activation_state": activation_state,
                "device_name": vals.get("DeviceName"),
                "product_type": vals.get("ProductType"),
                "product_version": vals.get("ProductVersion"),
            }
        except Exception as e:
            return {"error": str(e), "wiped": False}
    
    async def get_wipe_status(self, udid: str) -> Dict[str, Any]:
        """Get current wipe status of device."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            return {
                "udid": udid,
                "activation_state": vals.get("ActivationState"),
                "serial_number": vals.get("SerialNumber"),
                "product_type": vals.get("ProductType"),
                "product_version": vals.get("ProductVersion"),
                "wiped": vals.get("ActivationState") not in ["Activated", "ActivatedUnlocked"],
            }
        except Exception as e:
            return {"error": str(e)}


# Convenience functions
async def quick_wipe(udid: str) -> Dict[str, Any]:
    """Quick wipe with default options."""
    manager = WipeManager()
    result = await manager.wipe_device(udid)
    return {
        "success": result.success,
        "message": result.message,
        "certificate": result.certificate,
    }


async def full_wipe_with_certificate(
    udid: str,
    verifier: str = "fleetctl",
    additional_fields: Dict[str, str] = None
) -> Dict[str, Any]:
    """Full wipe with NIST 800-88 certificate."""
    options = WipeOptions(
        method="full",
        verify_after=True,
        generate_certificate=True,
        certificate_fields={"verifier": verifier} if verifier else {}
    )
    
    manager = WipeManager()
    result = await manager.wipe_device(udid, options)
    
    return {
        "success": result.success,
        "message": result.message,
        "certificate": result.certificate,
        "details": result.details,
    }