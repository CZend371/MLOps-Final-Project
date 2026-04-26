"""
SQS Consumer for ML inference.

Lifecycle:
  1. On startup, download model.pkl from S3 and load it into memory.
  2. Poll SQS in a loop using long-polling (WaitTimeSeconds=20).
  3. For each message: parse features, run model.predict(), write prediction
     JSON to S3, then delete the message from the queue.
  4. Graceful shutdown on SIGTERM / SIGINT.
"""

import json
import logging
import os
import signal
import sys
import tempfile
from datetime import datetime, timezone

import boto3
import joblib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

S3_BUCKET = os.environ["S3_BUCKET_NAME"]
SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
S3_MODEL_KEY = os.environ.get("S3_MODEL_KEY", "model.pkl")

_running = True


def _handle_shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received; finishing current batch then stopping.")
    _running = False


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


def load_model_from_s3(bucket: str, s3_key: str, region: str):
    """Download model.pkl from S3 into a temp file and load it with joblib."""
    s3 = boto3.client("s3", region_name=region)
    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        tmp_path = tmp.name

    s3.download_file(bucket, s3_key, tmp_path)
    model = joblib.load(tmp_path)
    os.unlink(tmp_path)
    logger.info("Model loaded from s3://%s/%s", bucket, s3_key)
    return model


def write_prediction_to_s3(
    prediction_payload: dict,
    bucket: str,
    record_id: str,
    region: str,
) -> str:
    """Write a single prediction JSON object to S3 at predictions/<record_id>.json."""
    s3 = boto3.client("s3", region_name=region)
    s3_key = f"predictions/{record_id}.json"
    body = json.dumps(prediction_payload)
    s3.put_object(Bucket=bucket, Key=s3_key, Body=body, ContentType="application/json")
    s3_uri = f"s3://{bucket}/{s3_key}"
    logger.info("Wrote prediction to %s", s3_uri)
    return s3_uri


def process_message(message: dict, model, sqs, bucket: str, region: str):
    """Parse a single SQS message, run inference, write to S3, delete the message."""
    receipt_handle = message["ReceiptHandle"]
    body = json.loads(message["Body"])

    record_id = body["record_id"]
    features = body["features"]

    prediction = int(model.predict([features])[0])
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "record_id": record_id,
        "prediction": prediction,
        "timestamp": timestamp,
    }

    write_prediction_to_s3(payload, bucket, record_id, region)

    sqs.delete_message(
        QueueUrl=SQS_QUEUE_URL,
        ReceiptHandle=receipt_handle,
    )
    logger.info("Processed and deleted message for record_id=%s", record_id)


def poll_loop(model, sqs):
    """Main polling loop: read messages from SQS and process them until shutdown."""
    logger.info("Starting SQS poll loop. Queue: %s", SQS_QUEUE_URL)
    while _running:
        response = sqs.receive_message(
            QueueUrl=SQS_QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )

        messages = response.get("Messages", [])
        if not messages:
            logger.debug("No messages received; polling again.")
            continue

        logger.info("Received %d message(s)", len(messages))
        for message in messages:
            try:
                process_message(message, model, sqs, S3_BUCKET, AWS_REGION)
            except Exception:
                logger.exception(
                    "Failed to process message (ReceiptHandle=%s); leaving on queue for retry.",
                    message.get("ReceiptHandle", "?"),
                )

    logger.info("Poll loop exited cleanly.")


def main():
    logger.info("Consumer starting up.")
    model = load_model_from_s3(S3_BUCKET, S3_MODEL_KEY, AWS_REGION)
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    poll_loop(model, sqs)
    logger.info("Consumer shut down.")


if __name__ == "__main__":
    main()
