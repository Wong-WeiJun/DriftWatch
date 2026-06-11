"""Tests for app.core.config."""

from unittest.mock import patch

import pytest

from app.core.config import Settings, get_settings, settings


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.APP_NAME == "DriftWatch"
        assert s.ENV == "development"
        assert s.DEBUG is True
        assert s.AWS_REGION == "ap-southeast-2"
        assert s.AWS_ACCOUNT_ID == ""
        assert s.TF_STATE_BUCKET == ""
        assert s.TF_STATE_KEY == "terraform.tfstate"
        assert s.DYNAMODB_TABLE_NAME == "driftwatch"
        assert s.SNS_TOPIC_ARN == ""
        assert s.API_V1_STR == "/api/v1"
        assert s.SCAN_INTERVAL_HOURS == 3

    def test_terraform_state_bucket_property(self):
        s = Settings()
        assert s.TERRAFORM_STATE_BUCKET == s.TF_STATE_BUCKET

    def test_terraform_state_key_property(self):
        s = Settings()
        assert s.TERRAFORM_STATE_KEY == s.TF_STATE_KEY

    def test_env_override(self):
        """Simulate setting via env file."""
        with patch.dict("os.environ", {"APP_NAME": "TestDriftWatch"}, clear=False):
            s = Settings()
            assert s.APP_NAME == "TestDriftWatch"

    def test_extra_fields_ignored(self):
        """Extra config attributes should be silently ignored."""
        s = Settings(_some_extra="value")
        # Should not raise
        assert s.APP_NAME == "DriftWatch"

    def test_aws_endpoint_url_none(self):
        """AWS_ENDPOINT_URL should default to None."""
        s = Settings()
        assert s.AWS_ENDPOINT_URL is None


class TestGetSettings:
    def test_lru_cache(self):
        """get_settings should return the same cached instance."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestModuleLevelSettings:
    def test_settings_import(self):
        """The module-level settings should be usable."""
        assert settings.APP_NAME == "DriftWatch"
