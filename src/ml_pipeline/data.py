import json
import pandas as pd
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split


def load_breast_cancer_data() -> pd.DataFrame:
    """Load the sklearn breast cancer dataset as a DataFrame with a target column."""
    dataset = load_breast_cancer(as_frame=True)
    df = dataset.frame
    df["target"] = dataset.target
    print(f"[data] Loaded breast cancer dataset: {len(df)} records, {df.shape[1]} columns")
    return df


def split_data(
    df: pd.DataFrame,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple:
    """Split dataframe into train/test feature and label arrays."""
    X = df.drop(columns=["target"])
    y = df["target"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )
    print(f"[data] Split: {len(X_train)} train, {len(X_test)} test records")
    return X_train, X_test, y_train, y_test


def get_test_records(X_test: pd.DataFrame) -> list:
    """Convert test feature DataFrame into a list of SQS-ready message dicts."""
    records = []
    for i, (_, row) in enumerate(X_test.iterrows()):
        record_id = f"sample_{i:03d}"
        records.append({
            "record_id": record_id,
            "features": row.tolist(),
        })
    print(f"[data] Generated {len(records)} test records for queuing")
    return records


def serialize_splits_for_xcom(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    y_test: pd.Series,
) -> dict:
    """Serialize train/test splits to JSON-safe dicts for Airflow XCom."""
    return {
        "X_train": X_train.values.tolist(),
        "X_test": X_test.values.tolist(),
        "y_train": y_train.tolist(),
        "y_test": y_test.tolist(),
        "feature_names": list(X_train.columns),
    }
