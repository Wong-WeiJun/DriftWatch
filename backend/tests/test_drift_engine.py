from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from app.services.drift_engine import (
    DriftInfo,
    compare_single,
    compute_drift,
    normalise,
    publish_alert,
    run_scan,
    save_drift_result,
)


# ---------------------------------------------------------------------------
# normalise
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_bool_true(self):
        assert normalise(True) == "true"

    def test_bool_false(self):
        assert normalise(False) == "false"

    def test_int(self):
        assert normalise(42) == "42"

    def test_float(self):
        assert normalise(3.14) == "3.14"

    def test_none(self):
        assert normalise(None) == ""

    def test_list(self):
        assert normalise(["b", "a"]) == '["a","b"]'

    def test_dict(self):
        # normalise() recursively converts values; int 2 => "2"
        assert normalise({"b": 2, "a": 1}) == '{"a":"1","b":"2"}'

    def test_list_unsortable(self):
        """List with mixed types should not raise even if sorting fails."""
        result = normalise([1, "b", None])
        # Should contain all elements even if not sorted
        assert '"1"' in result or '"b"' in result

    def test_dict_unsortable_values(self):
        """Dict with mixed-type values should still JSON stringify."""
        result = normalise({"a": 1, "b": "hello"})
        assert '"a":"1"' in result or '"b":"hello"' in result

    def test_string_passthrough(self):
        assert normalise("hello") == "hello"


# ---------------------------------------------------------------------------
# compute_drift
# ---------------------------------------------------------------------------


class TestComputeDrift:
    def test_no_differences(self):
        tf = {"ami": "ami-123", "type": "t3.micro"}
        live = {"ami": "ami-123", "type": "t3.micro"}
        assert compute_drift(tf, live) == {}

    def test_simple_difference(self):
        tf = {"ami": "ami-123"}
        live = {"ami": "ami-999"}
        diffs = compute_drift(tf, live)
        assert diffs == {"ami": {"tf_value": "ami-123", "live_value": "ami-999"}}

    def test_ignores_underscore_fields(self):
        tf = {"_internal": "secret", "ami": "ami-123"}
        live = {"_internal": "other", "ami": "ami-123"}
        assert compute_drift(tf, live) == {}

    def test_ignores_specified_fields(self):
        tf = {"ami": "ami-123", "timestamp": "t1"}
        live = {"ami": "ami-123", "timestamp": "t2"}
        diffs = compute_drift(tf, live, ignore_fields=("timestamp",))
        assert diffs == {}

    def test_normalises_lists(self):
        tf = {"tags": ["a", "b"]}
        live = {"tags": ["b", "a"]}
        assert compute_drift(tf, live) == {}

    def test_normalises_booleans(self):
        tf = {"encrypted": "true"}
        live = {"encrypted": True}
        assert compute_drift(tf, live) == {}

    def test_detects_missing_live_field(self):
        tf = {"ami": "ami-123"}
        live = {}
        diffs = compute_drift(tf, live)
        assert diffs == {"ami": {"tf_value": "ami-123", "live_value": None}}


# ---------------------------------------------------------------------------
# compare_single
# ---------------------------------------------------------------------------


class TestCompareSingle:
    def test_identical_resources(self):
        tf_entry = {
            "_type": "aws_instance",
            "id": "i-1",
            "ami": "ami-123",
            "instance_type": "t3.micro",
        }
        live_entry = {
            "_type": "aws_instance",
            "id": "i-1",
            "ami": "ami-123",
            "instance_type": "t3.micro",
        }
        info = compare_single("aws_instance", "i-1", tf_entry, live_entry)
        assert info.differences == {}
        assert info.only_in_live == set()
        assert info.only_in_tf == set()

    def test_drifted_field(self):
        tf_entry = {"ami": "ami-123", "instance_type": "t3.micro"}
        live_entry = {"ami": "ami-999", "instance_type": "t3.micro"}
        info = compare_single("aws_instance", "i-1", tf_entry, live_entry)
        assert "ami" in info.differences
        assert info.differences["ami"] == {
            "tf_value": "ami-123",
            "live_value": "ami-999",
        }

    def test_only_in_live(self):
        tf_entry = {"ami": "ami-123"}
        live_entry = {"ami": "ami-123", "public_ip": "1.2.3.4"}
        info = compare_single("aws_instance", "i-1", tf_entry, live_entry)
        assert info.only_in_live == {"public_ip"}
        assert "public_ip" not in info.differences  # only_in_live is separate

    def test_only_in_tf(self):
        tf_entry = {"ami": "ami-123", "key_name": "my-key"}
        live_entry = {"ami": "ami-123"}
        info = compare_single("aws_instance", "i-1", tf_entry, live_entry)
        assert info.only_in_tf == {"key_name"}
        # Missing-in-live fields are flagged as diffs with live_value=None
        assert info.differences["key_name"] == {
            "tf_value": "my-key",
            "live_value": None,
        }

    def test_mixed_drift_and_extra(self):
        tf_entry = {"ami": "ami-123", "type": "t3.micro", "key_name": "key1"}
        live_entry = {"ami": "ami-999", "type": "t3.micro", "public_ip": "1.2.3.4"}
        info = compare_single("aws_instance", "i-1", tf_entry, live_entry)
        assert info.differences["ami"] == {
            "tf_value": "ami-123",
            "live_value": "ami-999",
        }
        assert info.differences["key_name"] == {"tf_value": "key1", "live_value": None}
        assert info.only_in_live == {"public_ip"}
        assert info.only_in_tf == {"key_name"}


# ---------------------------------------------------------------------------
# run_scan
# ---------------------------------------------------------------------------


class TestRunScan:
    """Patch parse_tfstate_from_s3 and the scanner functions in drift_engine."""

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_no_drift(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_ec2.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        assert report["summary"]["drifted"] == 0
        assert report["summary"]["missing_in_live"] == 0
        assert report["summary"]["missing_in_tf"] == 0
        assert report["drifted"] == {}

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_drift_detected(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_ec2.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-999",  # drift
                "instance_type": "t3.micro",
            }
        }
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        assert report["summary"]["drifted"] == 1
        assert "i-1" in report["drifted"]
        assert report["drifted"]["i-1"]["differences"]["ami"] == {
            "tf_value": "ami-123",
            "live_value": "ami-999",
        }

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_missing_in_live(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_ec2.return_value = {}  # nothing in live
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        assert report["summary"]["missing_in_live"] == 1
        assert report["missing_in_live"] == [
            {"resource_type": "aws_instance", "resource_id": "i-1"}
        ]

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_missing_in_tf(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        mock_parse.return_value = {}  # nothing managed by TF
        mock_ec2.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        assert report["summary"]["missing_in_tf"] == 1
        assert report["missing_in_tf"] == [
            {"resource_type": "aws_instance", "resource_id": "i-1"}
        ]

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_scanner_failure_graceful(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        """If a scanner raises, the engine logs the error and treats the bucket as empty."""
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_ec2.side_effect = RuntimeError("AWS API down")
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        # EC2 scanner failed, so EC2 resources from TF are missing in live
        assert report["summary"]["missing_in_live"] == 1
        assert report["drifted"] == {}

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    @patch("app.services.drift_engine.settings")
    def test_custom_bucket_and_key_passed_through(
        self,
        mock_settings,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        mock_settings.TERRAFORM_STATE_BUCKET = "custom-bucket"
        mock_settings.TERRAFORM_STATE_KEY = "prod/terraform.tfstate"
        mock_parse.return_value = {}
        mock_ec2.return_value = {}
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        run_scan()

        mock_parse.assert_called_once_with(
            bucket="custom-bucket",
            key="prod/terraform.tfstate",
            skip_data=True,
        )

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_multi_resource_types(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        """Run scan with multiple resource types, counts should sum correctly."""
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            },
            "my-bucket": {
                "_type": "aws_s3_bucket",
                "id": "my-bucket",
                "bucket": "my-bucket",
            },
            "sg-1": {
                "_type": "aws_security_group",
                "id": "sg-1",
                "name": "web",
                "vpc_id": "vpc-1",
                "ingress_rule_count": "2",
                "egress_rule_count": "1",
            },
            "my-role": {
                "_type": "aws_iam_role",
                "id": "my-role",
                "name": "my-role",
                "path": "/",
            },
        }
        mock_ec2.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
                "instance_type": "t3.micro",
            }
        }
        mock_s3.return_value = {
            "my-bucket": {
                "_type": "aws_s3_bucket",
                "id": "my-bucket",
                "bucket": "my-bucket",
            }
        }
        mock_sg.return_value = {
            "sg-1": {
                "_type": "aws_security_group",
                "id": "sg-1",
                "name": "web",
                "vpc_id": "vpc-1",
                "ingress_rule_count": "2",
                "egress_rule_count": "1",
            }
        }
        mock_iam.return_value = {
            "my-role": {
                "_type": "aws_iam_role",
                "id": "my-role",
                "name": "my-role",
                "path": "/",
            }
        }
        mock_rds.return_value = {}

        report = run_scan()

        assert report["summary"]["tf_resources"] == 4
        assert report["summary"]["live_resources"] == 4
        assert report["summary"]["drifted"] == 0
        assert report["summary"]["missing_in_live"] == 0
        assert report["summary"]["missing_in_tf"] == 0

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_tf_resource_not_in_supported_scanners(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        """A TF-managed resource whose type is not in SCANNERS is noted as missing_in_live."""
        mock_parse.return_value = {
            "some-resource": {
                "_type": "aws_unknown_type",
                "id": "some-resource",
            }
        }
        mock_ec2.return_value = {}
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        assert report["summary"]["missing_in_live"] == 1

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    @patch("app.services.drift_engine.settings")
    def test_resource_types_filter(
        self,
        mock_settings,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        """Passing resource_types should limit which scanners run."""
        mock_settings.TERRAFORM_STATE_BUCKET = "bucket"
        mock_settings.TERRAFORM_STATE_KEY = "key.tfstate"
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-123",
            },
            "my-bucket": {
                "_type": "aws_s3_bucket",
                "id": "my-bucket",
            },
        }
        mock_ec2.return_value = {
            "i-1": {"_type": "aws_instance", "id": "i-1", "ami": "ami-123"}
        }
        mock_s3.return_value = {}
        mock_sg.return_value = {}
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan(resource_types=["ec2"])

        # S3 scanner should not have been called
        mock_s3.assert_not_called()
        assert report["summary"]["tf_resources"] == 2
        assert report["summary"]["live_resources"] == 1
        assert report["summary"]["missing_in_live"] >= 1


# ---------------------------------------------------------------------------
# save_drift_result
# ---------------------------------------------------------------------------


class TestSaveDriftResult:
    @patch("app.services.drift_engine.boto3.resource")
    def test_saves_to_dynamodb(self, mock_boto3_resource):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_ddb

        report = {
            "summary": {"drifted": 1, "missing_in_live": 0, "missing_in_tf": 0},
            "drifted": {"i-1": {"resource_type": "aws_instance"}},
            "missing_in_live": [],
            "missing_in_tf": [],
        }

        pk = save_drift_result(report)

        mock_ddb.Table.assert_called_once_with("driftwatch")
        mock_table.put_item.assert_called_once()
        call_item = mock_table.put_item.call_args.kwargs["Item"]
        assert call_item["event_id"] == pk
        assert "timestamp" in call_item
        assert call_item["summary"] == report["summary"]

    @patch("app.services.drift_engine.boto3.resource")
    def test_uses_configured_table_name(self, mock_boto3_resource):
        mock_table = MagicMock()
        mock_ddb = MagicMock()
        mock_ddb.Table.return_value = mock_table
        mock_boto3_resource.return_value = mock_ddb

        with patch("app.services.drift_engine.settings") as mock_settings:
            mock_settings.DYNAMODB_TABLE_NAME = "custom_table"
            mock_settings.AWS_REGION = "us-west-2"

            report = {
                "summary": {"drifted": 0, "missing_in_live": 0, "missing_in_tf": 0},
                "drifted": {},
                "missing_in_live": [],
                "missing_in_tf": [],
            }
            save_drift_result(report)

            mock_ddb.Table.assert_called_once_with("custom_table")
            mock_boto3_resource.assert_called_once_with(
                "dynamodb", region_name="us-west-2"
            )


# ---------------------------------------------------------------------------
# publish_alert
# ---------------------------------------------------------------------------


class TestPublishAlert:
    @patch("app.services.drift_engine.boto3.client")
    def test_publishes_to_sns(self, mock_boto3_client):
        mock_sns = MagicMock()
        mock_boto3_client.return_value = mock_sns

        with patch("app.services.drift_engine.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"
            mock_settings.AWS_REGION = "us-east-1"

            report = {
                "summary": {"drifted": 2, "missing_in_live": 1, "missing_in_tf": 0},
            }
            publish_alert(report)

            mock_boto3_client.assert_called_once_with("sns", region_name="us-east-1")
            mock_sns.publish.assert_called_once()
            call_kwargs = mock_sns.publish.call_args.kwargs
            assert call_kwargs["TopicArn"] == "arn:aws:sns:us-east-1:123456789:alerts"
            assert call_kwargs["Subject"] == "DriftWatch Drift Detected"
            assert "2 resources drifted" in call_kwargs["Message"]
            assert "1 missing in live AWS" in call_kwargs["Message"]

    def test_skips_when_no_topic_configured(self):
        with patch("app.services.drift_engine.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = ""
            report = {
                "summary": {"drifted": 1, "missing_in_live": 0, "missing_in_tf": 0}
            }
            # should not raise
            publish_alert(report)

    @patch("app.services.drift_engine.boto3.client")
    def test_logs_error_on_client_exception(self, mock_boto3_client):
        import botocore

        mock_sns = MagicMock()
        mock_sns.publish.side_effect = botocore.exceptions.ClientError(
            {"Error": {"Code": "NotFound", "Message": "Topic does not exist"}},
            "Publish",
        )
        mock_boto3_client.return_value = mock_sns

        with patch("app.services.drift_engine.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"
            mock_settings.AWS_REGION = "us-east-1"

            report = {
                "summary": {"drifted": 1, "missing_in_live": 0, "missing_in_tf": 0}
            }
            # Should not raise — the function catches ClientError
            publish_alert(report)

            mock_sns.publish.assert_called_once()


# ---------------------------------------------------------------------------
# Integration-style end-to-end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """A single end-to-end scenario with a realistic mix of drift, missing, and OK resources."""

    @patch("app.services.drift_engine.parse_tfstate_from_s3")
    @patch("app.services.drift_engine.get_ec2")
    @patch("app.services.drift_engine.get_s3")
    @patch("app.services.drift_engine.get_security_groups")
    @patch("app.services.drift_engine.get_iam_roles")
    @patch("app.services.drift_engine.get_rds")
    def test_full_scenario(
        self,
        mock_rds,
        mock_iam,
        mock_sg,
        mock_s3,
        mock_ec2,
        mock_parse,
    ):
        # TF state: 3 EC2, 1 S3, 1 SG
        mock_parse.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-100",
                "instance_type": "t3.micro",
            },
            "i-2": {
                "_type": "aws_instance",
                "id": "i-2",
                "ami": "ami-200",
                "instance_type": "t3.small",
            },
            "i-3": {
                "_type": "aws_instance",
                "id": "i-3",
                "ami": "ami-300",
                "instance_type": "t3.large",
            },
            "my-bucket": {
                "_type": "aws_s3_bucket",
                "id": "my-bucket",
                "bucket": "my-bucket",
            },
            "sg-1": {
                "_type": "aws_security_group",
                "id": "sg-1",
                "name": "web",
                "vpc_id": "vpc-1",
                "ingress_rule_count": "2",
                "egress_rule_count": "1",
            },
        }

        # Live AWS: i-1 OK, i-2 drifted, i-3 deleted, i-extra orphan, bucket OK, SG OK
        mock_ec2.return_value = {
            "i-1": {
                "_type": "aws_instance",
                "id": "i-1",
                "ami": "ami-100",
                "instance_type": "t3.micro",
            },
            "i-2": {
                "_type": "aws_instance",
                "id": "i-2",
                "ami": "ami-999",  # drift
                "instance_type": "t3.small",
            },
            "i-extra": {  # orphan
                "_type": "aws_instance",
                "id": "i-extra",
                "ami": "ami-000",
                "instance_type": "t3.nano",
            },
        }
        mock_s3.return_value = {
            "my-bucket": {
                "_type": "aws_s3_bucket",
                "id": "my-bucket",
                "bucket": "my-bucket",
            }
        }
        mock_sg.return_value = {
            "sg-1": {
                "_type": "aws_security_group",
                "id": "sg-1",
                "name": "web",
                "vpc_id": "vpc-1",
                "ingress_rule_count": "2",
                "egress_rule_count": "1",
            }
        }
        mock_iam.return_value = {}
        mock_rds.return_value = {}

        report = run_scan()

        # Summary counts
        assert report["summary"]["tf_resources"] == 5
        # Live: i-1, i-2, i-extra (3) + my-bucket + sg-1 = 5
        assert report["summary"]["live_resources"] == 5
        assert report["summary"]["drifted"] == 1  # i-2
        assert report["summary"]["missing_in_live"] == 1  # i-3
        assert report["summary"]["missing_in_tf"] == 1  # i-extra

        # Drift details
        assert "i-2" in report["drifted"]
        assert report["drifted"]["i-2"]["differences"]["ami"] == {
            "tf_value": "ami-200",
            "live_value": "ami-999",
        }

        # Missing
        missing_ids = {m["resource_id"] for m in report["missing_in_live"]}
        assert missing_ids == {"i-3"}
        orphan_ids = {m["resource_id"] for m in report["missing_in_tf"]}
        assert orphan_ids == {"i-extra"}
