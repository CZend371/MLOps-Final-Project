import os
import sys
import json

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

# Make src/ importable from the DAGs folder
sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from ml_pipeline.data import (
    load_breast_cancer_data,
    split_data,
    get_test_records,
    serialize_splits_for_xcom,
)
from ml_pipeline.model import train_model, save_model, upload_model_to_s3
from ml_pipeline.queue import publish_records_to_sqs

MODEL_LOCAL_PATH = "models/model.pkl"
S3_MODEL_KEY = "model.pkl"

default_args = {
    "owner": "airflow",
    "retries": 1,
}

with DAG(
    dag_id="ml_training_and_inference_pipeline",
    default_args=default_args,
    description="Train breast cancer classifier, upload to S3, and queue test records in SQS",
    schedule_interval=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:

    def _load_and_split_data(**kwargs):
        """Load breast cancer dataset, split into train/test, push splits via XCom."""
        df = load_breast_cancer_data()
        X_train, X_test, y_train, y_test = split_data(df)
        splits = serialize_splits_for_xcom(X_train, X_test, y_train, y_test)
        kwargs["ti"].xcom_push(key="splits", value=splits)
        print(f"[dag] Pushed splits to XCom: {len(splits['X_train'])} train, {len(splits['X_test'])} test")

    load_and_split_task = PythonOperator(
        task_id="load_and_split_data",
        python_callable=_load_and_split_data,
        provide_context=True,
    )

    def _train_model(**kwargs):
        """Pull train data from XCom, train LogisticRegression, save model locally."""
        splits = kwargs["ti"].xcom_pull(task_ids="load_and_split_data", key="splits")
        X_train = splits["X_train"]
        y_train = splits["y_train"]

        model = train_model(X_train, y_train)
        save_model(model, path=MODEL_LOCAL_PATH)
        print(f"[dag] Model saved locally to {MODEL_LOCAL_PATH}")

    train_task = PythonOperator(
        task_id="train_model",
        python_callable=_train_model,
        provide_context=True,
    )

    def _upload_model_to_s3(**kwargs):
        """Upload the locally saved model to S3."""
        bucket = os.environ["S3_BUCKET_NAME"]
        s3_uri = upload_model_to_s3(
            local_path=MODEL_LOCAL_PATH,
            bucket=bucket,
            s3_key=S3_MODEL_KEY,
        )
        print(f"[dag] Model uploaded to {s3_uri}")

    upload_task = PythonOperator(
        task_id="upload_model_to_s3",
        python_callable=_upload_model_to_s3,
        provide_context=True,
    )

    def _publish_to_sqs(**kwargs):
        """Pull test records from XCom and publish one SQS message per record."""
        splits = kwargs["ti"].xcom_pull(task_ids="load_and_split_data", key="splits")
        X_test = splits["X_test"]

        # Reconstruct records with sequential IDs
        records = [
            {"record_id": f"sample_{i:03d}", "features": row}
            for i, row in enumerate(X_test)
        ]

        queue_url = os.environ["SQS_QUEUE_URL"]
        count = publish_records_to_sqs(records, queue_url)
        print(f"[dag] Published {count} messages to SQS")

    publish_task = PythonOperator(
        task_id="publish_to_sqs",
        python_callable=_publish_to_sqs,
        provide_context=True,
    )

    load_and_split_task >> train_task >> upload_task >> publish_task
