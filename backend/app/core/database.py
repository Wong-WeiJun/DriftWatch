import logging
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_dynamodb = None


def get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource(
            "dynamodb",
            region_name=settings.AWS_REGION,
            endpoint_url=settings.DYNAMODB_ENDPOINT_URL,
        )
    return _dynamodb


def init_db():
    try:
        logger.info(f"Checking if table '{settings.DYNAMODB_TABLE_NAME}' exists")
        table = dynamodb.create_table(
            TableName=settings.DYNAMODB_TABLE_NAME,
            KeySchema=[
                {"AttributeName": "scan_id", "KeyType": "HASH"},
                {"AttributeName": "resource_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "scan_id", "AttributeType": "S"},
                {"AttributeName": "resource_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        logger.info(f"Creating table '{settings.DYNAMODB_TABLE_NAME}'")
        table.meta.client.get_waiter("table_exists").wait(
            TableName=settings.DYNAMODB_TABLE_NAME
        )
        logger.info(
            f"Table '{settings.DYNAMODB_TABLE_NAME}' is active and ready to use"
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            logger.info(
                f"Table {settings.DYNAMODB_TABLE_NAME} already exists. Skipping"
            )
        else:
            logger.error(f"Received Error while initializing database: {e}")
            raise e
