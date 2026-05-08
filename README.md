# MLOps Final Project

A distributed machine learning system that trains a breast cancer classifier and processes inference jobs asynchronously using Airflow, S3, SQS, and ECS.

## Architecture

```
Training Pipeline (Airflow DAG: training_pipeline)
  └─► train_and_upload
        ├─ loads breast cancer dataset
        ├─ splits 80/20 (random_state=42)
        ├─ trains LogisticRegression
        └─ uploads model.pkl → S3

Inference Pipeline (Airflow DAG: inference_pipeline)
  └─► publish_test_records
        ├─ loads breast cancer dataset
        ├─ splits 80/20 (same random_state=42)
        └─ publishes one SQS message per test record (~114 messages)

SQS Queue ──► ECS Fargate Tasks (1..N consumers)
                    ├─ loads model.pkl from S3 on startup
                    ├─ runs model.predict() per message
                    └─ writes predictions/sample_NNN.json → S3
```

## Repository Structure

```
MLOps-Final-Project/
├── dags/
│   ├── training_dag.py          # Airflow DAG: train model and upload to S3
│   └── inference_dag.py         # Airflow DAG: publish test records to SQS
├── src/
│   └── ml_pipeline/
│       ├── data.py              # Dataset loading and splitting
│       ├── model.py             # Training, serialization, S3 upload
│       └── queue.py             # SQS message publishing
├── consumer/
│   ├── consumer.py              # SQS consumer (polls, infers, writes to S3)
│   ├── requirements.txt
│   └── Dockerfile
├── ecs/
│   └── task-definition.json     # ECS Fargate task definition (envsubst placeholders)
├── .env.example                 # Environment variable template
├── requirements.txt             # Airflow + pipeline deps
├── setup_airflow.sh             # Local Airflow bootstrap
└── README.md
```

## Prerequisites

- Python 3.11 (compatible with 3.10 and 3.12 — update the Airflow constraints URL in `requirements.txt` to match your version)
- AWS CLI configured (`aws configure`) with access to S3, SQS, ECR, and ECS
- Docker (for building the consumer image)
- IAM permissions: `s3:PutObject`, `s3:GetObject`, `sqs:SendMessage`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `ecr:*`, `ecs:*`

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
# Edit .env and fill in S3_BUCKET_NAME, SQS_QUEUE_URL, and ECR_IMAGE_URI
```

Load them into your shell:

```bash
export $(grep -v '#' .env | xargs)
```

## Airflow Setup

### 1. Create and Activate a Virtual Environment

```bash
python3.11 -m venv venv
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

### 5. Run the DAGs

There are two independent DAGs. Run them in order: training first, then inference.

**Step 1 — Training Pipeline**

In the Airflow UI trigger `training_pipeline`, or via CLI:

```bash
airflow dags trigger training_pipeline
```

| Task | Description |
|------|-------------|
| `train_and_upload` | Loads dataset, trains LogisticRegression, saves `models/model.pkl`, uploads to S3 |

**Step 2 — Inference Pipeline** (run after training completes)

```bash
airflow dags trigger inference_pipeline
```

| Task | Description |
|------|-------------|
| `publish_test_records` | Loads dataset, splits identically to training, sends ~114 SQS messages |

## Consumer (ECS)

### 1. Build the Docker Image

```bash
cd consumer/
docker build -t sqs-consumer:latest .
```

### 2. Push to ECR

```bash
# Create the ECR repository (first time only)
aws ecr create-repository --repository-name <your-repo-name> --region us-east-1

# Authenticate Docker to ECR
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin \
    <account-id>.dkr.ecr.us-east-1.amazonaws.com

# Tag and push
docker tag sqs-consumer:latest \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/<your-repo-name>:latest

docker push \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com/<your-repo-name>:latest
```

Add the full image URI to your `.env` as `ECR_IMAGE_URI`.

### 3. Configure the ECS Task Definition

The ECS cluster, task definition, and service are all created via the AWS Console. When configuring the task definition container, add the following environment variables:

| Key | Value |
|-----|-------|
| `S3_BUCKET_NAME` | Your S3 bucket name (e.g. `mlops-final-project-cz`) |
| `SQS_QUEUE_URL` | Your full SQS queue URL |
| `AWS_DEFAULT_REGION` | `us-east-1` |
| `S3_MODEL_KEY` | `model.pkl` |

### 4. Scale Up

To run multiple consumers in parallel, increase the **Number of tasks** when running the task. Each task independently polls SQS and processes messages. Because predictions are written to unique S3 keys (`predictions/sample_NNN.json`) and messages are deleted only after a successful write, concurrent tasks process different records without conflicts.

### 5. View Logs

Consumer logs are written to CloudWatch automatically. View them in the AWS Console under:
**CloudWatch → Log Groups → /ecs/\<your-log-group\>**

Or via CLI:
```bash
aws logs tail /ecs/<your-log-group-name> --follow
```

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

The test set contains approximately 114 records (20% of 569), so you should see ~114 prediction files when all consumers have finished.

## Key Design Notes

- **Two independent DAGs:** `training_pipeline` and `inference_pipeline` are decoupled -- each loads and splits the dataset on its own. The split is identical because both use the same sklearn built-in dataset and `random_state=42`.
- **At-least-once delivery:** SQS messages are deleted only after the prediction is successfully written to S3. If a consumer task fails mid-processing, the SQS visibility timeout expires and the message becomes visible again for retry.
- **No write conflicts:** each prediction is stored at a unique S3 key (`predictions/<record_id>.json`), so multiple ECS tasks never overwrite each other.
- **Long-polling:** the consumer uses `WaitTimeSeconds=20` to reduce SQS API calls and cost.
- **Graceful shutdown:** the consumer catches `SIGTERM` (sent by ECS during task termination) and stops polling after finishing the current batch.
- **Model loaded once:** the model is downloaded from S3 and deserialized once on task startup, not per message.
