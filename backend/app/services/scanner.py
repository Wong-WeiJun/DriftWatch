import boto3
from typing import Any
from app.core.config import settings

_session = boto3.Session(region_name=settings.AWS_REGION)



def get_s3() -> dict[str, dict[str, Any]]:
    s3 = _session.client("s3")
    buckets ={}
    for bucket in s3.list_buckets().get("Buckets", []):
        name = bucket["Name"]
        versioning = "Disabled"
        try:
            v = s3.get_bucket_versioning(Bucket=name)
            versioning = v.get("Status", "Disabled")
        except Exception:
            pass
        public_block = {}
        try:
            pb = s3.get_public_access_block(Bucket=name)
            public_block = pb.get("PublicAccessBlockConfiguration", {})
        except Exception:
            pass

        buckets[name] = {
            "_type": "aws_s3_bucket",
            "id": name,
            "bucket": name,
            "versioning": versioning,
            "block_public_acls": str(public_block.get("BlockPublicAcls", False)),
            "block_public_policy": str(public_block.get("BlockPublicPolicy", False))
        }
    return buckets



