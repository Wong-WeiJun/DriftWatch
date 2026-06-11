"""Tests for app.services.notifier."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from app.services.notifier import get_sns, publish_drift_alert
from models.drift import DriftEvent, ScanResult


# ---------------------------------------------------------------------------
# get_sns
# ---------------------------------------------------------------------------


class TestGetSns:
    @patch("app.services.notifier.boto3.client")
    def test_creates_client(self, mock_boto_client):
        mock_sns = MagicMock()
        mock_boto_client.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.AWS_REGION = "us-east-1"
            mock_settings.AWS_ENDPOINT_URL = "http://localhost:4566"

            result = get_sns()
            assert result is mock_sns
            mock_boto_client.assert_called_once_with(
                "sns",
                region_name="us-east-1",
                endpoint_url="http://localhost:4566",
            )

    @patch("app.services.notifier._sns", None)
    @patch("app.services.notifier.boto3.client")
    def test_caching(self, mock_boto_client):
        """get_sns should cache the client."""
        mock_sns = MagicMock()
        mock_boto_client.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.AWS_REGION = "ap-southeast-2"
            mock_settings.AWS_ENDPOINT_URL = None

            sns1 = get_sns()
            sns2 = get_sns()
            assert sns1 is sns2
            mock_boto_client.assert_called_once_with(
                "sns", region_name="ap-southeast-2"
            )


# ---------------------------------------------------------------------------
# publish_drift_alert
# ---------------------------------------------------------------------------


class TestPublishDriftAlert:
    @patch("app.services.notifier.get_sns")
    def test_publishes_with_drift(self, mock_get_sns):
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            event = DriftEvent(
                scan_id="scan-123",
                resource_id="i-1",
                resource_type="ec2",
                attribute="instance_type",
                expected="t3.micro",
                actual="t3.large",
                severity="high",
                detected_at=datetime(2026, 6, 8, 10, 0, 0, tzinfo=timezone.utc),
            )
            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=5,
                drifts_found=1,
                status="completed",
                drift_events=[event],
            )
            publish_drift_alert(result)

            mock_sns.publish.assert_called_once()
            call_kwargs = mock_sns.publish.call_args.kwargs
            assert call_kwargs["TopicArn"] == "arn:aws:sns:us-east-1:123456789:alerts"
            assert "HIGH" in call_kwargs["Subject"]
            assert "1 drift" in call_kwargs["Subject"]
            assert "Driftwatch detected 1 drift(s)" in call_kwargs["Message"]

    @patch("app.services.notifier.get_sns")
    def test_skips_when_no_topic_arn(self, mock_get_sns):
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = ""

            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=5,
                drifts_found=2,
                status="completed",
                drift_events=[
                    DriftEvent(
                        scan_id="scan-123",
                        resource_id="i-1",
                        resource_type="ec2",
                        attribute="ami",
                        expected="ami-a",
                        actual="ami-b",
                        severity="high",
                    )
                ],
            )
            publish_drift_alert(result)

            mock_sns.publish.assert_not_called()

    @patch("app.services.notifier.get_sns")
    def test_skips_when_no_drift(self, mock_get_sns):
        """No drift found should skip alert regardless of topic ARN."""
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=5,
                drifts_found=0,
                status="completed",
                drift_events=[],
            )
            publish_drift_alert(result)

            mock_sns.publish.assert_not_called()

    @patch("app.services.notifier.get_sns")
    def test_subject_with_medium_severity(self, mock_get_sns):
        """When no high drift, subject should say MEDIUM."""
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            event = DriftEvent(
                scan_id="scan-123",
                resource_id="b-1",
                resource_type="s3",
                attribute="versioning",
                expected="Enabled",
                actual="Disabled",
                severity="medium",
            )
            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=3,
                drifts_found=1,
                status="completed",
                drift_events=[event],
            )
            publish_drift_alert(result)

            call_kwargs = mock_sns.publish.call_args.kwargs
            assert "[MEDIUM]" in call_kwargs["Subject"]
            assert "1 drift" in call_kwargs["Subject"]

    @patch("app.services.notifier.get_sns")
    def test_subject_with_low_severity(self, mock_get_sns):
        """When only low drift, subject should say LOW."""
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            event = DriftEvent(
                scan_id="scan-123",
                resource_id="b-1",
                resource_type="s3",
                attribute="tags",
                expected="{}",
                actual='{"env": "prod"}',
                severity="low",
            )
            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=3,
                drifts_found=1,
                status="completed",
                drift_events=[event],
            )
            publish_drift_alert(result)

            call_kwargs = mock_sns.publish.call_args.kwargs
            assert "[LOW]" in call_kwargs["Subject"]

    @patch("app.services.notifier.get_sns")
    def test_multiple_events_summarized(self, mock_get_sns):
        """Multiple events should be summarized by severity."""
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            events = [
                DriftEvent(
                    scan_id="scan-123",
                    resource_id="i-1",
                    resource_type="ec2",
                    attribute="instance_type",
                    expected="t3.micro",
                    actual="t3.large",
                    severity="high",
                ),
                DriftEvent(
                    scan_id="scan-123",
                    resource_id="sg-1",
                    resource_type="security_group",
                    attribute="ingress_rule_count",
                    expected="2",
                    actual="3",
                    severity="high",
                ),
                DriftEvent(
                    scan_id="scan-123",
                    resource_id="b-1",
                    resource_type="s3",
                    attribute="versioning",
                    expected="Enabled",
                    actual="Disabled",
                    severity="medium",
                ),
            ]
            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=10,
                drifts_found=3,
                status="completed",
                drift_events=events,
            )
            publish_drift_alert(result)

            msg = mock_sns.publish.call_args.kwargs["Message"]
            assert "High severity:     2" in msg
            assert "Medium severity:   1" in msg
            assert "Low severity:      0" in msg

    @patch("app.services.notifier.get_sns")
    def test_truncates_long_event_list(self, mock_get_sns):
        """More than 10 events should show first 10 with '... and X more'."""
        mock_sns = MagicMock()
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            events = []
            for i in range(15):
                events.append(
                    DriftEvent(
                        scan_id="scan-123",
                        resource_id=f"i-{i}",
                        resource_type="ec2",
                        attribute="instance_type",
                        expected="t3.micro",
                        actual="t3.large",
                        severity="high",
                    )
                )
            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=15,
                drifts_found=15,
                status="completed",
                drift_events=events,
            )
            publish_drift_alert(result)

            msg = mock_sns.publish.call_args.kwargs["Message"]
            assert "... and 5 more drift(s) not shown." in msg

    @patch("app.services.notifier.get_sns")
    def test_client_error_logs_but_does_not_raise(self, mock_get_sns):
        """ClientError from SNS should be logged but not propagate."""
        mock_sns = MagicMock()
        mock_sns.publish.side_effect = ClientError(
            {"Error": {"Code": "NotFound", "Message": "Topic does not exist"}},
            "Publish",
        )
        mock_get_sns.return_value = mock_sns

        with patch("app.services.notifier.settings") as mock_settings:
            mock_settings.SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789:alerts"

            event = DriftEvent(
                scan_id="scan-123",
                resource_id="i-1",
                resource_type="ec2",
                attribute="ami",
                expected="ami-a",
                actual="ami-b",
                severity="high",
            )
            result = ScanResult(
                scan_id="scan-123",
                resource_scanned=5,
                drifts_found=1,
                status="completed",
                drift_events=[event],
            )
            # Should not raise
            publish_drift_alert(result)

            mock_sns.publish.assert_called_once()
