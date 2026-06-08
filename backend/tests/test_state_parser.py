import json
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
import botocore

from app.services.state_parser import (
    _parse_state_dict,
    fetch_tfstate_from_s3,
    find_latest_tfstate_key,
    get_state_summary_from_s3,
    list_tfstate_objects,
    parse_tfstate_from_s3,
)


@pytest.fixture
def sample_raw_state():
    """Return a minimal raw Terraform state dict."""
    return {
        "version": 4,
        "terraform_version": "1.8.0",
        "serial": 42,
        "lineage": "abcd-1234",
        "resources": [
            {
                "mode": "managed",
                "type": "aws_instance",
                "name": "web",
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [
                    {
                        "schema_version": 0,
                        "attributes": {
                            "id": "i-123",
                            "ami": "ami-abc",
                            "instance_type": "t3.micro",
                            "subnet_id": "subnet-1",
                            "vpc_id": "vpc-1",
                            "tags": {"Name": "web"},
                        },
                    }
                ],
            },
            {
                "mode": "data",
                "type": "aws_caller_identity",
                "name": "current",
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [{"schema_version": 0, "attributes": {"id": "12345"}}],
            },
        ],
    }


# ---------------------------------------------------------------------------
# _parse_state_dict
# ---------------------------------------------------------------------------


class TestParseStateDict:
    def test_basic(self, sample_raw_state):
        resources = _parse_state_dict(sample_raw_state, skip_data=True)
        assert "i-123" in resources
        assert resources["i-123"]["_type"] == "aws_instance"
        assert resources["i-123"]["ami"] == "ami-abc"
        assert resources["i-123"]["tags"] == {"Name": "web"}

    def test_skips_data_resources(self, sample_raw_state):
        resources = _parse_state_dict(sample_raw_state, skip_data=True)
        data_keys = [k for k in resources if resources[k]["_type"].startswith("data.")]
        assert len(data_keys) == 0

    def test_includes_data_when_skip_false(self, sample_raw_state):
        resources = _parse_state_dict(sample_raw_state, skip_data=False)
        data_keys = [k for k in resources if resources[k]["_mode"] == "data"]
        assert len(data_keys) == 1

    def test_no_instances(self):
        state = {"version": 4, "resources": []}
        resources = _parse_state_dict(state)
        assert resources == {}


# ---------------------------------------------------------------------------
# fetch_tfstate_from_s3
# ---------------------------------------------------------------------------


class TestFetchTfstateFromS3:
    @patch("app.services.state_parser.boto3.client")
    def test_successful_fetch(self, mock_boto_client, sample_raw_state):
        mock_s3 = MagicMock()
        body = BytesIO(json.dumps(sample_raw_state).encode("utf-8"))
        mock_s3.get_object.return_value = {"Body": body}
        mock_boto_client.return_value = mock_s3

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "test-bucket"
            mock_settings.AWS_REGION = "us-east-1"

            result = fetch_tfstate_from_s3(key="terraform.tfstate")

        mock_boto_client.assert_called_once_with("s3", region_name="us-east-1")
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="terraform.tfstate"
        )
        assert result["version"] == 4
        assert result["serial"] == 42

    @patch("app.services.state_parser.boto3.client")
    def test_custom_bucket_arg(self, mock_boto_client, sample_raw_state):
        mock_s3 = MagicMock()
        body = BytesIO(json.dumps(sample_raw_state).encode("utf-8"))
        mock_s3.get_object.return_value = {"Body": body}
        mock_boto_client.return_value = mock_s3

        result = fetch_tfstate_from_s3(
            bucket="override-bucket", key="dev/state.tfstate"
        )

        mock_s3.get_object.assert_called_once_with(
            Bucket="override-bucket", Key="dev/state.tfstate"
        )

    def test_raises_when_bucket_is_default_placeholder(self):
        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "state_bucket"
            with pytest.raises(ValueError, match="No S3 bucket configured"):
                fetch_tfstate_from_s3()

    def test_raises_when_bucket_empty(self):
        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = ""
            with pytest.raises(ValueError, match="No S3 bucket configured"):
                fetch_tfstate_from_s3()

    @patch("app.services.state_parser.boto3.client")
    def test_propagates_client_error(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )
        mock_boto_client.return_value = mock_s3

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "valid-bucket"
            mock_settings.AWS_REGION = "us-east-1"
            with pytest.raises(botocore.exceptions.ClientError):
                fetch_tfstate_from_s3(key="missing.tfstate")


# ---------------------------------------------------------------------------
# list_tfstate_objects
# ---------------------------------------------------------------------------


class TestListTfstateObjects:
    @patch("app.services.state_parser.boto3.client")
    def test_lists_tfstate_files(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "terraform.tfstate",
                        "Size": 1234,
                        "LastModified": datetime(
                            2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc
                        ),
                        "ETag": '"abc123"',
                    },
                    {
                        "Key": "readme.txt",
                        "Size": 100,
                        "LastModified": datetime(
                            2024, 1, 15, 9, 0, 0, tzinfo=timezone.utc
                        ),
                        "ETag": '"def456"',
                    },
                    {
                        "Key": "dev/terraform.tfstate",
                        "Size": 5678,
                        "LastModified": datetime(
                            2024, 1, 16, 8, 0, 0, tzinfo=timezone.utc
                        ),
                        "ETag": '"ghi789"',
                    },
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_s3

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "test-bucket"
            mock_settings.AWS_REGION = "us-east-1"

            objs = list_tfstate_objects()

        assert len(objs) == 2
        assert objs[0]["key"] == "dev/terraform.tfstate"  # newest first
        assert objs[1]["key"] == "terraform.tfstate"
        assert objs[0]["etag"] == "ghi789"
        assert objs[0]["last_modified"] == "2024-01-16T08:00:00+00:00"

    @patch("app.services.state_parser.boto3.client")
    def test_empty_bucket(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]
        mock_s3.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_s3

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "test-bucket"
            objs = list_tfstate_objects()

        assert objs == []

    @patch("app.services.state_parser.boto3.client")
    def test_respects_prefix(self, mock_boto_client):
        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]
        mock_s3.get_paginator.return_value = mock_paginator
        mock_boto_client.return_value = mock_s3

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "test-bucket"
            list_tfstate_objects(prefix="prod/")

        mock_paginator.paginate.assert_called_once_with(
            Bucket="test-bucket", Prefix="prod/"
        )


# ---------------------------------------------------------------------------
# find_latest_tfstate_key
# ---------------------------------------------------------------------------


class TestFindLatestTfstateKey:
    @patch("app.services.state_parser.list_tfstate_objects")
    def test_returns_newest(self, mock_list):
        mock_list.return_value = [
            {"key": "dev/terraform.tfstate"},
            {"key": "terraform.tfstate"},
        ]
        assert find_latest_tfstate_key() == "dev/terraform.tfstate"

    @patch("app.services.state_parser.list_tfstate_objects")
    def test_returns_none_when_empty(self, mock_list):
        mock_list.return_value = []
        assert find_latest_tfstate_key() is None


# ---------------------------------------------------------------------------
# parse_tfstate_from_s3
# ---------------------------------------------------------------------------


class TestParseTfstateFromS3:
    @patch("app.services.state_parser.fetch_tfstate_from_s3")
    def test_explicit_key(self, mock_fetch, sample_raw_state):
        mock_fetch.return_value = sample_raw_state

        resources = parse_tfstate_from_s3(bucket="b", key="k.tfstate")

        mock_fetch.assert_called_once_with(bucket="b", key="k.tfstate")
        assert "i-123" in resources

    @patch("app.services.state_parser.find_latest_tfstate_key")
    @patch("app.services.state_parser.fetch_tfstate_from_s3")
    def test_auto_discovers_key(self, mock_fetch, mock_find, sample_raw_state):
        mock_find.return_value = "latest.tfstate"
        mock_fetch.return_value = sample_raw_state

        resources = parse_tfstate_from_s3(bucket="b")

        mock_find.assert_called_once_with(bucket="b")
        mock_fetch.assert_called_once_with(bucket="b", key="latest.tfstate")

    @patch("app.services.state_parser.find_latest_tfstate_key")
    def test_raises_when_no_key_found(self, mock_find):
        mock_find.return_value = None

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "test-bucket"
            with pytest.raises(FileNotFoundError, match="No .tfstate file found"):
                parse_tfstate_from_s3()


# ---------------------------------------------------------------------------
# get_state_summary_from_s3
# ---------------------------------------------------------------------------


class TestGetStateSummaryFromS3:
    @patch("app.services.state_parser.fetch_tfstate_from_s3")
    def test_returns_full_summary(self, mock_fetch, sample_raw_state):
        mock_fetch.return_value = sample_raw_state

        with patch("app.services.state_parser.settings") as mock_settings:
            mock_settings.TF_STATE_BUCKET = "test-bucket"
            mock_settings.AWS_REGION = "us-east-1"

            summary = get_state_summary_from_s3(key="state.tfstate")

        assert summary["bucket"] == "test-bucket"
        assert summary["key"] == "state.tfstate"
        assert summary["version"] == 4
        assert summary["terraform_version"] == "1.8.0"
        assert summary["serial"] == 42
        assert summary["lineage"] == "abcd-1234"
        assert summary["resource_blocks"] == 2
        assert summary["managed_blocks"] == 1
        assert summary["data_blocks"] == 1
        assert summary["resource_count"] == 1
        assert "i-123" in summary["resources"]
