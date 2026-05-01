import os
import sys

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from ml_pipeline.data import load_breast_cancer_data, split_data
from ml_pipeline.queue import publish_records_to_sqs

default_args = {
    "owner": "airflow",
    "retries": 1,
}


def _publish_test_records(**kwargs):
    """Load dataset, split identically to training, publish test records to SQS."""
    df = load_breast_cancer_data()
    X_train, X_test, y_train, y_test = split_data(df)

    records = [
        {"record_id": f"sample_{i:03d}", "features": row.tolist()}
        for i, row in enumerate(X_test.itertuples(index=False))
    ]

    queue_url = os.environ["SQS_QUEUE_URL"]
    count = publish_records_to_sqs(records, queue_url)
    print(f"[inference_dag] Published {count} messages to SQS")


with DAG(
    dag_id="inference_pipeline",
    default_args=default_args,
    description="Publish breast cancer test records to SQS for async inference by ECS consumers",
    schedule_interval=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:

    publish_test_records = PythonOperator(
        task_id="publish_test_records",
        python_callable=_publish_test_records,
        provide_context=True,
    )
