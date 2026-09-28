"""
Tests for report_generator module.
"""

import pytest
import json
import csv
import io
from fleetctl.report_generator import (
    ReportGenerator,
    JSONReportGenerator,
    CSVReportGenerator,
    HTMLReportGenerator,
    PDFReportGenerator,
    ReportGeneratorFactory,
    ReportConfig,
    generate_device_report,
)


class TestReportConfig:
    """Tests for ReportConfig dataclass."""
    
    def test_default_config(self):
        config = ReportConfig()
        assert config.title == "Device Report"
        assert config.include_timestamp is True
        assert config.include_errors is True
        assert config.include_unavailable is True
        assert config.company_name is None
        assert config.logo_path is None
    
    def test_custom_config(self):
        config = ReportConfig(
            title="Custom Report",
            company_name="Test Corp",
            include_timestamp=False,
        )
        assert config.title == "Custom Report"
        assert config.company_name == "Test Corp"
        assert config.include_timestamp is False


class TestJSONReportGenerator:
    """Tests for JSONReportGenerator."""
    
    @pytest.fixture
    def generator(self):
        return JSONReportGenerator()
    
    @pytest.fixture
    def sample_devices(self):
        return [
            {
                "udid": "test-udid-1",
                "identity": {
                    "device_name": "iPhone 15",
                    "product_type": "iPhone15,2",
                    "product_version": "17.4.1",
                },
                "status": {
                    "is_supervised": True,
                    "password_protected": True,
                },
                "resources": {
                    "total_data_capacity": 128 * 1024**3,
                    "data_available": 64 * 1024**3,
                },
                "metadata": {
                    "chip": "A16",
                },
                "errors": {},
            },
            {
                "udid": "test-udid-2",
                "identity": {
                    "device_name": "iPad Pro",
                    "product_type": "iPad14,1",
                    "product_version": "17.4.1",
                },
                "status": {
                    "is_supervised": False,
                    "password_protected": True,
                },
                "resources": {
                    "total_data_capacity": 256 * 1024**3,
                    "data_available": 128 * 1024**3,
                },
                "metadata": {
                    "chip": "M2",
                },
                "errors": {"disk_usage": "permission denied"},
            },
        ]
    
    def test_generate_json(self, generator, sample_devices):
        config = ReportConfig(title="Test Report")
        result = generator.generate(sample_devices, config)
        
        data = json.loads(result.decode("utf-8"))
        
        assert data["metadata"]["title"] == "Test Report"
        assert data["metadata"]["device_count"] == 2
        assert len(data["devices"]) == 2
        assert data["devices"][0]["udid"] == "test-udid-1"
        assert data["devices"][1]["udid"] == "test-udid-2"
    
    def test_get_extension(self, generator):
        assert generator.get_extension() == "json"


class TestCSVReportGenerator:
    """Tests for CSVReportGenerator."""
    
    @pytest.fixture
    def generator(self):
        return CSVReportGenerator()
    
    @pytest.fixture
    def sample_devices(self):
        return [
            {
                "udid": "test-udid-1",
                "identity": {
                    "device_name": "iPhone 15",
                    "product_type": "iPhone15,2",
                    "product_version": "17.4.1",
                },
                "status": {
                    "is_supervised": True,
                    "password_protected": True,
                },
                "metadata": {
                    "chip": "A16",
                },
            },
        ]
    
    def test_generate_csv(self, generator, sample_devices):
        config = ReportConfig(title="Test Report")
        result = generator.generate(sample_devices, config)
        
        content = result.decode("utf-8")
        lines = content.strip().split("\n")
        
        assert len(lines) == 2  # header + 1 data row
        assert "udid" in lines[0]
        assert "identity_device_name" in lines[0]
        assert "test-udid-1" in lines[1]
    
    def test_get_extension(self, generator):
        assert generator.get_extension() == "csv"


class TestHTMLReportGenerator:
    """Tests for HTMLReportGenerator."""
    
    @pytest.fixture
    def generator(self):
        return HTMLReportGenerator()
    
    @pytest.fixture
    def sample_devices(self):
        return [
            {
                "udid": "test-udid-1",
                "identity": {
                    "device_name": "iPhone 15",
                    "product_type": "iPhone15,2",
                    "product_version": "17.4.1",
                },
                "status": {
                    "is_supervised": True,
                    "password_protected": True,
                },
                "resources": {
                    "total_data_capacity": 128 * 1024**3,
                    "data_available": 64 * 1024**3,
                },
                "metadata": {
                    "chip": "A16",
                },
                "errors": {},
            },
        ]
    
    def test_generate_html(self, generator, sample_devices):
        config = ReportConfig(title="Test Report")
        result = generator.generate(sample_devices, config)
        
        html = result.decode("utf-8")
        
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "Test Report" in html
        assert "iPhone 15" in html
        assert "A16" in html
        assert "Supervised" in html
    
    def test_get_extension(self, generator):
        assert generator.get_extension() == "html"


class TestReportGeneratorFactory:
    """Tests for ReportGeneratorFactory."""
    
    def test_create_json(self):
        generator = ReportGeneratorFactory.create("json")
        assert isinstance(generator, JSONReportGenerator)
    
    def test_create_csv(self):
        generator = ReportGeneratorFactory.create("csv")
        assert isinstance(generator, CSVReportGenerator)
    
    def test_create_html(self):
        generator = ReportGeneratorFactory.create("html")
        assert isinstance(generator, HTMLReportGenerator)
    
    def test_create_pdf(self):
        generator = ReportGeneratorFactory.create("pdf")
        assert isinstance(generator, PDFReportGenerator)
    
    def test_invalid_format(self):
        with pytest.raises(ValueError):
            ReportGeneratorFactory.create("invalid")
    
    def test_generate_report(self):
        devices = [
            {
                "udid": "test-udid-1",
                "identity": {"device_name": "iPhone 15"},
                "status": {"is_supervised": True},
                "metadata": {"chip": "A16"},
            },
        ]
        
        result = ReportGeneratorFactory.generate_report(
            devices, "json", ReportConfig(title="Test")
        )
        
        data = json.loads(result.decode("utf-8"))
        assert data["metadata"]["device_count"] == 1
    
    def test_get_supported_formats(self):
        formats = ReportGeneratorFactory.get_supported_formats()
        assert "json" in formats
        assert "csv" in formats
        assert "html" in formats
        assert "pdf" in formats


class TestGenerateDeviceReport:
    """Tests for generate_device_report convenience function."""
    
    def test_generate_device_report(self):
        devices = [
            {
                "udid": "test-udid-1",
                "identity": {"device_name": "iPhone 15"},
                "status": {"is_supervised": True},
                "metadata": {"chip": "A16"},
            },
        ]
        
        result = generate_device_report(
            devices,
            format="json",
            title="Test Report",
            company_name="Test Corp",
        )
        
        data = json.loads(result.decode("utf-8"))
        assert data["metadata"]["title"] == "Test Report"
        assert data["metadata"]["company"] == "Test Corp"
        assert data["metadata"]["device_count"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])