"""
Tests for config_writer module.
"""

import pytest
from fleetctl.config_writer import (
    ConfigWriter,
    CloudConfiguration,
    ConfigurationResult,
    SkipSetupOptions,
    create_enterprise_config,
    create_skip_setup_config,
    ConfigurationSource,
)


class TestCloudConfiguration:
    """Tests for CloudConfiguration dataclass."""
    
    def test_default_config(self):
        config = CloudConfiguration()
        assert config.allow_pairing is True
        assert config.cloud_configuration_ui_complete is True
        assert config.configuration_was_applied is True
        assert config.is_mdm_unremovable is False
        assert config.is_mandatory is False
        assert config.is_multi_user is False
        assert config.is_supervised is False
        assert config.post_setup_profile_was_installed is True
        assert config.skip_setup == []
    
    def test_custom_config(self):
        config = CloudConfiguration(
            allow_pairing=False,
            is_supervised=True,
            skip_setup=["Location", "AppleID"],
        )
        assert config.allow_pairing is False
        assert config.is_supervised is True
        assert config.skip_setup == ["Location", "AppleID"]


class TestSkipSetupOptions:
    """Tests for SkipSetupOptions class."""
    
    def test_all_options(self):
        assert "Location" in SkipSetupOptions.ALL
        assert "AppleID" in SkipSetupOptions.ALL
        assert "Passcode" in SkipSetupOptions.ALL
        assert len(SkipSetupOptions.ALL) > 10
    
    def test_minimal_options(self):
        assert "Location" in SkipSetupOptions.MINIMAL
        assert "AppleID" in SkipSetupOptions.MINIMAL
        assert "Passcode" in SkipSetupOptions.MINIMAL
        assert len(SkipSetupOptions.MINIMAL) == 6
    
    def test_enterprise_options(self):
        assert "Location" in SkipSetupOptions.ENTERPRISE
        assert "AppleID" in SkipSetupOptions.ENTERPRISE
        assert "Passcode" in SkipSetupOptions.ENTERPRISE
        assert "MDM" not in SkipSetupOptions.ENTERPRISE  # Not a valid option
    
    def test_custom_options(self):
        custom = SkipSetupOptions.custom("Location", "AppleID", "CustomOption")
        assert custom == ["Location", "AppleID", "CustomOption"]


class TestConfigCreation:
    """Tests for configuration creation helpers."""
    
    def test_create_enterprise_config(self):
        config = create_enterprise_config(
            organization_name="Test Corp",
            skip_setup=["Location", "AppleID"],
            supervised=True,
        )
        
        assert config.organization_name == "Test Corp"
        assert config.is_supervised is True
        assert config.is_mandatory is True
        assert config.skip_setup == ["Location", "AppleID"]
        assert config.is_supervised is True
    
    def test_create_skip_setup_config(self):
        config = create_skip_setup_config(
            skip_setup=["Location", "AppleID"],
            supervised=False,
        )
        
        assert config.skip_setup == ["Location", "AppleID"]
        assert config.is_supervised is False
        assert config.is_mandatory is False


class TestConfigWriter:
    """Tests for ConfigWriter class."""
    
    @pytest.fixture
    def writer(self):
        return ConfigWriter()
    
    def test_writer_initialization(self, writer):
        assert writer is not None
        assert hasattr(writer, '_pymobiledevice3_available')
    
    def test_writer_available_property(self, writer):
        # available mirrors whether the hard dependency is importable
        import importlib.util
        expected = importlib.util.find_spec("pymobiledevice3") is not None
        assert writer.available is expected
    
    def test_configuration_source_enum(self):
        assert ConfigurationSource.USER == 0
        assert ConfigurationSource.DEVICE == 1
        assert ConfigurationSource.MDM == 2
        assert ConfigurationSource.ENTERPRISE == 3


class TestConfigurationResult:
    """Tests for ConfigurationResult dataclass."""
    
    def test_success_result(self):
        result = ConfigurationResult(
            success=True,
            message="Success",
            details={"key": "value"},
        )
        assert result.success is True
        assert result.message == "Success"
        assert result.details == {"key": "value"}
        assert result.error_code is None
    
    def test_error_result(self):
        result = ConfigurationResult(
            success=False,
            message="Error occurred",
            error_code="ERROR_CODE",
            details={"error": "details"},
        )
        assert result.success is False
        assert result.message == "Error occurred"
        assert result.error_code == "ERROR_CODE"
        assert result.details == {"error": "details"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])