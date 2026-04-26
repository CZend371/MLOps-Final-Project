import os
import joblib
import boto3
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score


def train_model(
    X_train: list,
    y_train: list,
) -> LogisticRegression:
    """Train a logistic regression classifier and return the fitted model."""
    clf = LogisticRegression(max_iter=200)
    clf.fit(X_train, y_train)

    train_preds = clf.predict(X_train)
    train_acc = accuracy_score(y_train, train_preds)
    print(f"[model] Training accuracy: {train_acc:.4f}")

    return clf


def save_model(
    model: LogisticRegression,
    path: str = "models/model.pkl",
) -> str:
    """Serialize the model to disk using joblib."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    joblib.dump(model, path)
    print(f"[model] Saved model to {path}")
    return path


def upload_model_to_s3(
    local_path: str,
    bucket: str,
    s3_key: str = "model.pkl",
) -> str:
    """Upload the serialized model file to S3."""
    s3 = boto3.client("s3")
    s3.upload_file(local_path, bucket, s3_key)
    s3_uri = f"s3://{bucket}/{s3_key}"
    print(f"[model] Uploaded {local_path} -> {s3_uri}")
    return s3_uri
