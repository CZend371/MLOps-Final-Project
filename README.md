# MLOps Final Project

A distributed machine learning system that trains a breast cancer classifier and processes inference jobs asynchronously using Airflow, S3, SQS, and Kubernetes.

## Architecture

```
Airflow DAG
  └─► load_and_split_data
        └─► train_model  (LogisticRegression on breast cancer dataset)
              └─► upload_model_to_s3  (model.pkl → S3)
                    └─► publish_to_sqs  (one message per test record)

SQS Queue ──► Kubernetes Consumer Pods (1..N replicas)
                    ├─ loads model.pkl from S3 on startup
                    ├─ runs model.predict() per message
                    └─ writes predictions/sample_NNN.json → S3
```

## Repository Structure

```
MLOps-Final-Project/
├── dags/
│   └── ml_pipeline_dag.py       # Airflow DAG (training + SQS publish)
├── src/
│   └── ml_pipeline/
│       ├── data.py              # Dataset loading, splitting, record generation
│       ├── model.py             # Training, serialization, S3 upload
│       └── queue.py             # SQS message publishing
├── consumer/
│   ├── consumer.py              # SQS consumer (polls, infers, writes to S3)
│   ├── requirements.txt
│   └── Dockerfile
├── k8s/
│   └── consumer-deployment.yaml # Kubernetes Deployment manifest
├── .env.example                 # Environment variable template
├── requirements.txt             # Airflow + pipeline deps
├── setup_airflow.sh             # Local Airflow bootstrap
└── README.md
```

## Prerequisites

- Python 3.12
- AWS CLI configured (`aws configure`) with access to S3 and SQS
- Docker (for building the consumer image)
- `kubectl` + a running Kubernetes cluster (e.g. EKS, Minikube)
- IAM permissions: `s3:PutObject`, `s3:GetObject`, `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`

## AWS Setup

### 1. Create an S3 Bucket

```bash
aws s3 mb s3://<your-bucket-name> --region us-east-1
```

### 2. Create an SQS Queue

```bash
aws sqs create-queue --queue-name ml-inference-queue --region us-east-1
```

Copy the returned `QueueUrl` — you will need it below.

### 3. Set Environment Variables

```bash
cp .env.example .env
# Edit .env and fill in S3_BUCKET_NAME and SQS_QUEUE_URL
```

Export them in your current shell:

```bash
export S3_BUCKET_NAME=<your-bucket-name>
export SQS_QUEUE_URL=<your-sqs-queue-url>
export AWS_DEFAULT_REGION=us-east-1
```

## Airflow Setup

### 1. Create and Activate a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Initialize Airflow

```bash
source ./setup_airflow.sh
```

### 3. Create an Admin User (first time only)

```bash
airflow users create \
  --username admin \
  --firstname Admin \
  --lastname User \
  --role Admin \
  --email admin@example.com \
  --password admin
```

### 4. Start Airflow (two separate terminals)

Make sure the AWS environment variables are exported in both terminals before starting.

**Terminal 1 — Webserver:**
```bash
source venv/bin/activate
source ./setup_airflow.sh
airflow webserver --port 8080
```

**Terminal 2 — Scheduler:**
```bash
source venv/bin/activate
source ./setup_airflow.sh
airflow scheduler
```

Open the Airflow UI at [http://localhost:8080](http://localhost:8080).

### 5. Run the Pipeline DAG

In the UI, find the DAG `ml_training_and_inference_pipeline` and trigger it manually.

Or via CLI:

```bash
airflow dags trigger ml_training_and_inference_pipeline
```

The DAG runs four tasks in order:

| Task | Description |
|------|-------------|
| `load_and_split_data` | Loads breast cancer dataset, splits 80/20, pushes to XCom |
| `train_model` | Trains LogisticRegression, saves `models/model.pkl` locally |
| `upload_model_to_s3` | Uploads `model.pkl` to `s3://<bucket>/model.pkl` |
| `publish_to_sqs` | Sends one SQS message per test record (~114 messages) |

## Consumer (Kubernetes)

### 1. Build the Docker Image

```bash
cd consumer/
docker build -t sqs-consumer:latest .
```

### 2. Push to a Container Registry

**ECR example:**
```bash
aws ecr create-repository --repository-name sqs-consumer --region us-east-1

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    <account-id>.dkr.ecr.us-east-1.amazonaws.com

docker tag sqs-consumer:latest \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/sqs-consumer:latest

docker push \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/sqs-consumer:latest
```

### 3. Update the Kubernetes Manifest

Edit `k8s/consumer-deployment.yaml` and replace the placeholder values:

| Placeholder | Value |
|-------------|-------|
| `<PLACEHOLDER_ECR_IMAGE_URI>` | Your full ECR image URI |
| `<PLACEHOLDER_S3_BUCKET_NAME>` | Your S3 bucket name |
| `<PLACEHOLDER_SQS_QUEUE_URL>` | Your SQS queue URL |

### 4. Deploy to Kubernetes

```bash
kubectl apply -f k8s/consumer-deployment.yaml
```

Verify the pod is running:

```bash
kubectl get pods -l app=sqs-consumer
kubectl logs -l app=sqs-consumer --follow
```

### 5. Scale the Deployment

```bash
kubectl scale deployment sqs-consumer --replicas=3
kubectl get pods -l app=sqs-consumer
```

Multiple replicas will compete to pull messages from SQS. Because each prediction is written to a unique file (`predictions/sample_NNN.json`) and messages are deleted only after a successful S3 write, concurrent consumers process different records without conflicts.

## Verifying Results

### Check predictions in S3

```bash
aws s3 ls s3://<your-bucket-name>/predictions/
```

Download and inspect a prediction:

```bash
aws s3 cp s3://<your-bucket-name>/predictions/sample_000.json - | python3 -m json.tool
```

Expected format:

```json
{
  "record_id": "sample_000",
  "prediction": 1,
  "timestamp": "2026-04-15T12:00:00Z"
}
```

### Count completed predictions

```bash
aws s3 ls s3://<your-bucket-name>/predictions/ | wc -l
```

The test set contains approximately 114 records (20% of 569), so you should see ~114 prediction files.

## Key Design Notes

- **At-least-once delivery:** SQS messages are deleted only after the prediction is successfully written to S3. If the consumer crashes mid-processing, the SQS visibility timeout expires and the message becomes visible again for retry.
- **No write conflicts:** Each prediction is stored at a unique S3 key (`predictions/<record_id>.json`), so multiple consumer replicas never overwrite each other.
- **Long-polling:** The consumer uses `WaitTimeSeconds=20` to reduce SQS API calls and cost.
- **Graceful shutdown:** The consumer catches `SIGTERM` (sent by Kubernetes during pod termination) and stops polling after finishing the current batch.
- **Model loaded once:** The model is downloaded from S3 and deserialized once on pod startup, not per message, to minimize latency and S3 costs.
