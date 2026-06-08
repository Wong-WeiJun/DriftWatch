import os
import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
