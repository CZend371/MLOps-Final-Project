import os
import sys

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from ml_pipeline.data import load_breast_cancer_data, split_data
from ml_pipeline.model import train_model, save_model, upload_model_to_s3

MODEL_LOCAL_PATH = "models/model.pkl"
S3_MODEL_KEY = "model.pkl"

default_args = {
    "owner": "airflow",
    "retries": 1,
}


def _train_and_upload(**kwargs):
    """Load dataset, train model, save locally, and upload to S3."""
    df = load_breast_cancer_data()
    X_train, X_test, y_train, y_test = split_data(df)

    model = train_model(X_train.values.tolist(), y_train.tolist())
    save_model(model, path=MODEL_LOCAL_PATH)

    bucket = os.environ["S3_BUCKET_NAME"]
    upload_model_to_s3(local_path=MODEL_LOCAL_PATH, bucket=bucket, s3_key=S3_MODEL_KEY)
    print(f"[training_dag] Model uploaded to s3://{bucket}/{S3_MODEL_KEY}")


with DAG(
    dag_id="training_pipeline",
    default_args=default_args,
    description="Load breast cancer dataset, train LogisticRegression, upload model.pkl to S3",
    schedule_interval=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:

    train_and_upload = PythonOperator(
        task_id="train_and_upload",
        python_callable=_train_and_upload,
        provide_context=True,
    )
