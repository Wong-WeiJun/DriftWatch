"""Tests for app.core.database."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from app.core.database import get_dynamodb, init_db


class TestGetDynamodb:
    @patch("app.core.database._dynamodb", None)
    @patch("app.core.database.boto3.resource")
    def test_creates_resource(self, mock_boto_resource):
        mock_ddb = MagicMock()
        mock_boto_resource.return_value = mock_ddb

        with patch("app.core.database.settings") as mock_settings:
            mock_settings.AWS_REGION = "us-west-2"
            mock_settings.AWS_ENDPOINT_URL = None

            ddb = get_dynamodb()
            assert ddb is mock_ddb
            mock_boto_resource.assert_called_once_with(
                "dynamodb", region_name="us-west-2", endpoint_url=None
            )

    @patch("app.core.database._dynamodb", None)
    @patch("app.core.database.boto3.resource")
    def test_uses_endpoint_url(self, mock_boto_resource):
        mock_ddb = MagicMock()
        mock_boto_resource.return_value = mock_ddb

        with patch("app.core.database.settings") as mock_settings:
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.AWS_ENDPOINT_URL = "http://localhost:4566"

            ddb = get_dynamodb()
            mock_boto_resource.assert_called_once_with(
                "dynamodb",
                region_name="us-east-1",
                endpoint_url="http://localhost:4566",
            )

    @patch("app.core.database._dynamodb", None)
    @patch("app.core.database.boto3.resource")
    def test_caching(self, mock_boto_resource):
        """Second call should reuse resource without calling boto3 again."""
        mock_ddb = MagicMock()
        mock_boto_resource.return_value = mock_ddb

        with patch("app.core.database.settings") as mock_settings:
            mock_settings.AWS_REGION = "ap-southeast-1"
            mock_settings.AWS_ENDPOINT_URL = None

            # Reset the module-level cache
            import app.core.database as db

            db._dynamodb = None
            ddb1 = get_dynamodb()
            ddb2 = get_dynamodb()
            assert ddb1 is ddb2
            mock_boto_resource.assert_called_once()


class TestInitDb:
    @patch("app.core.database.get_dynamodb")
    def test_creates_table(self, mock_get_dynamodb):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.create_table.return_value = mock_table
        mock_get_dynamodb.return_value = mock_ddb

        with patch("app.core.database.settings") as mock_settings:
            mock_settings.DYNAMODB_TABLE_NAME = "test_table"
            init_db()

        mock_ddb.create_table.assert_called_once()
        call_kwargs = mock_ddb.create_table.call_args.kwargs
        assert call_kwargs["TableName"] == "test_table"
        # Check KeySchema
        assert call_kwargs["KeySchema"] == [
            {"AttributeName": "scan_id", "KeyType": "HASH"},
            {"AttributeName": "resource_id", "KeyType": "RANGE"},
        ]
        # Check BillingMode
        assert call_kwargs["BillingMode"] == "PAY_PER_REQUEST"
        mock_table.meta.client.get_waiter.assert_called_once_with("table_exists")

    @patch("app.core.database.get_dynamodb")
    def test_skips_when_table_exists(self, mock_get_dynamodb):
        """Should gracefully skip if table already exists."""
        mock_ddb = MagicMock()
        error = ClientError(
            {"Error": {"Code": "ResourceInUseException", "Message": "Table exists"}},
            "CreateTable",
        )
        mock_ddb.create_table.side_effect = error
        mock_get_dynamodb.return_value = mock_ddb

        with patch("app.core.database.settings") as mock_settings:
            mock_settings.DYNAMODB_TABLE_NAME = "test_table"
            # Should not raise
            init_db()

    @patch("app.core.database.get_dynamodb")
    def test_raises_on_other_error(self, mock_get_dynamodb):
        """Should re-raise non-ResourceInUseException errors."""
        mock_ddb = MagicMock()
        error = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "No access"}},
            "CreateTable",
        )
        mock_ddb.create_table.side_effect = error
        mock_get_dynamodb.return_value = mock_ddb

        with patch("app.core.database.settings") as mock_settings:
            mock_settings.DYNAMODB_TABLE_NAME = "test_table"
            with pytest.raises(ClientError) as exc_info:
                init_db()
            assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
