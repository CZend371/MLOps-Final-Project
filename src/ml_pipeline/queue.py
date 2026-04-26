import json
import boto3


def publish_records_to_sqs(records: list, queue_url: str) -> int:
    """Send one SQS message per record. Returns the number of messages published."""
    sqs = boto3.client("sqs")
    published = 0

    for record in records:
        body = json.dumps({
            "record_id": record["record_id"],
            "features": record["features"],
        })
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=body,
        )
        published += 1

    print(f"[queue] Published {published} messages to SQS queue: {queue_url}")
    return published
