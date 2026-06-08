import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
from app.models.drift import ScanResult

logger = logginf.getLogger(__name__)

_sns = None


def get_sns():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns", region_name=settings.AWS_REGION)
    return _sns
