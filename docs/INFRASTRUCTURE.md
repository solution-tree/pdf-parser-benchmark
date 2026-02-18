# PLC Coach Infrastructure & Deployment Plan

**Version**: 1.0
**Date**: February 18, 2026
**Environment**: AWS (us-east-1)
**Target Phase**: MVP (Synthetic Data) → Production (FERPA-Compliant)

---

## Executive Summary

This document defines the infrastructure architecture for PLC Coach, designed to:
1. Support **MVP internal testing** (synthetic data, simple setup)
2. **Scale seamlessly to Beta/Production** with real student data (FERPA-compliant)
3. Minimize operational overhead while maintaining security and compliance
4. Use **Infrastructure-as-Code (Terraform)** for reproducibility

**Key Principle**: Build FERPA-ready from day one to avoid rip-and-replace at Beta launch.

---

## 1. Architecture Overview

### 1.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS Account (us-east-1)                  │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                      VPC (Private Network)               │   │
│  │  CIDR: 10.0.0.0/16                                       │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │  Public Subnet (us-east-1a)                         │ │   │
│  │  │  - NAT Gateway (for outbound traffic)               │ │   │
│  │  │  - Application Load Balancer (ALB)                  │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  │                           ↓                               │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │  Private Subnet (us-east-1a, us-east-1b)            │ │   │
│  │  │  - ECS Fargate Cluster (API Container)              │ │   │
│  │  │  - RDS PostgreSQL (Primary)                         │ │   │
│  │  │  - Qdrant EC2 Instance (Self-Hosted Vector DB)      │ │   │
│  │  │  - ElastiCache Redis (Cache Layer)                  │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │  Data Layer                                         │ │   │
│  │  │  - S3 (Backups, Logs, Audit Trail)                  │ │   │
│  │  │  - AWS Secrets Manager (API Keys, DB Credentials)   │ │   │
│  │  │  - AWS KMS (Encryption Keys)                        │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  │                                                           │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │  Monitoring & Logging                              │ │   │
│  │  │  - CloudWatch (Logs, Metrics, Alarms)               │ │   │
│  │  │  - CloudTrail (Audit Trail)                         │ │   │
│  │  │  - VPC Flow Logs (Network Traffic)                  │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              External Services (Outside VPC)             │   │
│  │  - OpenAI API (GPT-4 with zero-retention SDPA)          │   │
│  │  - Perplexity API (Web Search - Alpha+)                 │   │
│  │  - Route 53 (DNS)                                       │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. AWS Services & Configuration

### 2.1 Compute Layer

#### **Option A: MVP (Simple, Single Container)**
```
ECS Fargate (1 task)
- CPU: 1024 (1 vCPU)
- Memory: 2048 MB (2 GB)
- Cost: ~$30/month (always on)
```

**Rationale**: For internal testing with 5-10 users, one container is sufficient. Fargate is serverless (no EC2 management), scales automatically, and is FERPA-ready.

#### **Option B: Alpha → Production (Auto-Scaling)**
```
ECS Fargate (Auto-Scaling Group)
- Min: 1 task
- Max: 10 tasks
- Target CPU: 70%
- Cost: ~$30-300/month (scales with load)
```

**Rationale**: As real schools onboard (Beta/Prod), auto-scaling ensures availability. CloudWatch alarms trigger scale-up/down automatically.

---

### 2.2 Database Layer

#### **PostgreSQL (RDS)**

**MVP Configuration:**
```
Instance Type: db.t3.micro (free tier eligible)
Storage: 20 GB gp2
Backup: 7-day retention
Multi-AZ: No
Cost: ~$15/month
```

**Scaling Path:**
```
Beta/Prod: db.t3.small → db.r5.large
Multi-AZ: Yes (99.95% uptime requirement)
Read Replicas: Yes (for dashboards/analytics)
```

**Schema Design (FERPA-Ready):**
```sql
-- Core Tables
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  role ENUM('teacher', 'admin', 'system') NOT NULL,
  school_id UUID REFERENCES schools(id),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE schools (
  id UUID PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  dpa_signed_at TIMESTAMP,
  data_residency_requirement VARCHAR(100),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE queries (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  query_text VARCHAR(2000) NOT NULL,
  query_hash CHAR(64),  -- SHA-256 for PII detection
  answer_text TEXT,
  sources JSONB,  -- [{citation, page, sku}]
  confidence_score FLOAT,
  mode ENUM('corpus_first', 'hybrid') DEFAULT 'corpus_first',
  tokens_used INT,
  cost_usd DECIMAL(10, 6),
  response_time_ms INT,
  created_at TIMESTAMP DEFAULT NOW(),
  INDEX (user_id, created_at),
  INDEX (school_id, created_at)  -- For school admins
);

CREATE TABLE audit_log (
  id UUID PRIMARY KEY,
  event_type ENUM('query', 'access', 'data_export', 'deletion') NOT NULL,
  user_id UUID REFERENCES users(id),
  school_id UUID REFERENCES schools(id),
  resource_type VARCHAR(100),
  resource_id UUID,
  action VARCHAR(100),
  details JSONB,
  ip_address INET,
  created_at TIMESTAMP DEFAULT NOW(),
  INDEX (school_id, created_at),  -- For school audit trails
  INDEX (event_type, created_at)
);

-- Future: RBAC Tables
CREATE TABLE role_permissions (
  role VARCHAR(100),
  permission VARCHAR(100),
  PRIMARY KEY (role, permission)
);

CREATE TABLE user_permissions (
  user_id UUID REFERENCES users(id),
  permission VARCHAR(100),
  PRIMARY KEY (user_id, permission)
);
```

---

### 2.3 Vector Database: Qdrant

#### **MVP Configuration:**
```
Deployment: Single EC2 instance (t3.medium)
Storage: 50 GB gp2 volume
Memory: 2-4 GB allocated to Qdrant process
Cost: ~$30/month (compute) + ~$5/month (storage)
Snapshots: Daily to S3 (for backup/restore)
```

**Docker Container Setup:**
```yaml
# docker-compose.yml for Qdrant
version: '3.8'
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - ./qdrant_storage:/qdrant/storage
    environment:
      QDRANT_API_KEY: ${QDRANT_API_KEY}
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Collection Configuration:**
```python
# src/embed.py - Qdrant collection setup
from qdrant_client import QdrantClient, models

def create_collection(client: QdrantClient):
    client.create_collection(
        collection_name="plc_books",
        vectors_config=models.VectorParams(
            size=3072,  # text-embedding-3-large
            distance=models.Distance.COSINE,
            hnsw_config=models.HnswConfigDiff(
                m=16,  # Connections per node
                ef_construct=200,  # Build-time parameter
                full_scan_threshold=10000,
            ),
        ),
        # Ensure snapshot backups
        optimizers_config=models.OptimizersConfigDiff(
            snapshot_interval=3600,  # 1 hour snapshots
        ),
    )
```

**Scaling Path (Beta/Prod):**
```
High Availability Setup:
- 3 Qdrant nodes in EC2 Auto Scaling Group
- Network Load Balancer (Layer 4) for routing
- S3 snapshots every 4 hours
- Multi-AZ deployment (us-east-1a, us-east-1b, us-east-1c)
Cost: ~$300/month
```

---

### 2.4 Caching Layer: ElastiCache

#### **MVP:**
```
Engine: Redis 7 (compatible with redis-py)
Node Type: cache.t3.micro
Num Cache Nodes: 1
Cost: ~$10/month
```

**Rationale**: For MVP, single node is fine. No failover needed.

#### **Alpha → Production:**
```
Node Type: cache.r6g.large
Num Cache Nodes: 2 (multi-AZ replication)
Automatic failover: Enabled
Cost: ~$150/month
```

**Cache Configuration:**
```python
# src/cache.py - Redis setup
import redis.asyncio as redis
from functools import wraps
import hashlib
import json

async def get_redis() -> redis.Redis:
    return await redis.from_url(
        "rediss://localhost:6379",  # rediss:// for TLS encryption
        encoding="utf-8",
        decode_responses=True
    )

def make_cache_key(query: str, model: str, top_k: int) -> str:
    """Create SHA-256 cache key from query + config"""
    payload = f"{query}:{model}:{top_k}"
    return f"plc_kb:{hashlib.sha256(payload.encode()).hexdigest()}"

async def cache_query_result(
    r: redis.Redis,
    query: str,
    result: dict,
    ttl: int = 86400  # 24 hours
) -> None:
    """Cache query result with FERPA-aware TTL"""
    key = make_cache_key(query, result['model'], result['top_k'])
    await r.setex(key, ttl, json.dumps(result))

# Usage in src/api/routes.py
@app.post("/api/v1/query")
async def query(request: QueryRequest):
    cache_key = make_cache_key(request.query, config.LLM_MODEL, config.SIMILARITY_TOP_K)

    # Try cache first
    cached = await r.get(cache_key)
    if cached:
        return json.loads(cached)

    # Execute query (ingest.py, embed.py, rag.py)
    result = await execute_query(request.query)

    # Cache result
    await cache_query_result(r, request.query, result)

    return result
```

---

### 2.5 Secrets Management

#### **AWS Secrets Manager**

Store all sensitive data (NOT in `.env` or code):

```
Secrets to Store:
- OPENAI_API_KEY
- QDRANT_API_KEY
- DATABASE_URL (with password)
- REDIS_PASSWORD
- API_KEY (for authentication)
- PERPLEXITY_API_KEY (Alpha+)
```

**Terraform Configuration:**
```hcl
# terraform/secrets.tf
resource "aws_secretsmanager_secret" "openai_key" {
  name                    = "plc-coach/openai-api-key"
  recovery_window_in_days = 7  # Allow accidental deletion recovery
}

resource "aws_secretsmanager_secret_version" "openai_key" {
  secret_id     = aws_secretsmanager_secret.openai_key.id
  secret_string = var.openai_api_key
}

# ECS task reads secret at runtime via IAM role
```

**Application Code:**
```python
# src/config.py - Load secrets from Secrets Manager
import boto3
from botocore.exceptions import ClientError

def get_secret(secret_name: str) -> str:
    """Retrieve secret from AWS Secrets Manager"""
    client = boto3.client('secretsmanager', region_name='us-east-1')
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return response['SecretString']
    except ClientError as e:
        raise Exception(f"Failed to retrieve secret {secret_name}: {e}")

# In Config class
class Config(BaseSettings):
    OPENAI_API_KEY: str = Field(
        default_factory=lambda: get_secret("plc-coach/openai-api-key")
    )
    DATABASE_URL: str = Field(
        default_factory=lambda: get_secret("plc-coach/database-url")
    )
```

---

### 2.6 Storage & Backups: S3

```
Purpose:
- Backup Qdrant snapshots (daily)
- Backup PostgreSQL (automatic via RDS)
- Store audit logs (CloudWatch → S3)
- Store data exports (for FERPA compliance)

Bucket Configuration:
- Name: plc-coach-backups-{account-id}
- Versioning: Enabled
- Encryption: AES-256 (default)
- Access: Private (VPC endpoints only, no public access)
- Lifecycle: Move to Glacier after 90 days
- Cost: ~$1/month (minimal for 50 GB data)
```

---

### 2.7 Encryption & Key Management: AWS KMS

```
Encryption Strategy:

At Rest:
- EBS volumes: AWS KMS (customer-managed key)
- RDS: AWS KMS encryption
- S3: AWS KMS encryption
- ElastiCache: Encryption at rest enabled

In Transit:
- VPC traffic: AWS PrivateLink (no internet)
- OpenAI API: TLS 1.3
- Database: TLS 1.2+
- Redis: TLS with AUTH

KMS Key Rotation:
- Automatic yearly rotation
- CloudTrail logs all key usage
```

---

## 3. Security & FERPA Compliance

### 3.1 Network Security

#### **VPC Architecture:**
```
VPC (10.0.0.0/16)
├── Public Subnets (NAT Gateway, ALB only)
│   ├── us-east-1a (10.0.1.0/24)
│   └── us-east-1b (10.0.2.0/24)
├── Private Subnets (ECS, RDS, Qdrant, Redis)
│   ├── us-east-1a (10.0.11.0/24)
│   └── us-east-1b (10.0.12.0/24)
└── Security Groups
    ├── ALB (Allow 443 from internet)
    ├── ECS (Allow 8000 from ALB, port 443 to OpenAI)
    ├── RDS (Allow 5432 from ECS only)
    ├── Qdrant (Allow 6333 from ECS only)
    └── Redis (Allow 6379 from ECS only)
```

#### **Key Rules:**
```
✅ Allow: ECS → RDS (5432)
✅ Allow: ECS → Qdrant (6333)
✅ Allow: ECS → Redis (6379)
✅ Allow: ECS → OpenAI API (443)
❌ Deny: RDS, Qdrant, Redis ← Internet (no direct access)
❌ Deny: ECS from internet except via ALB (443)
```

---

### 3.2 Authentication & Authorization

#### **API Authentication (MVP):**
```
Simple API Key:
- Header: X-API-Key: {secret-key}
- Validate in middleware
- Rotate every 90 days

Rationale: MVP is internal-only, simple auth sufficient.
```

#### **Alpha/Beta: OAuth 2.0 (Google SSO)**
```python
# src/api/middleware.py - Google OAuth
from fastapi.security import OAuth2PasswordBearer
from google.oauth2 import id_token
from google.auth.transport import requests

async def verify_token(token: str):
    """Verify Google ID token"""
    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            requests.Request(),
            GOOGLE_CLIENT_ID
        )
        return idinfo['email']
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

#### **Beta/Prod: Role-Based Access Control (RBAC)**
```python
# src/api/rbac.py
from enum import Enum

class Role(str, Enum):
    TEACHER = "teacher"
    SCHOOL_ADMIN = "school_admin"
    DISTRICT_ADMIN = "district_admin"
    SYSTEM_ADMIN = "system_admin"

ROLE_PERMISSIONS = {
    Role.TEACHER: [
        "query:read",
        "query:create",
        "team:view_own",
    ],
    Role.SCHOOL_ADMIN: [
        "query:read",
        "school:view_analytics",
        "users:manage_school",
        "audit_log:read",
    ],
    Role.DISTRICT_ADMIN: [
        "query:read",
        "district:view_analytics",
        "users:manage_district",
        "audit_log:read",
    ],
}

async def enforce_rbac(current_user: User, required_permission: str):
    """Check if user has required permission"""
    permissions = ROLE_PERMISSIONS.get(current_user.role, [])
    if required_permission not in permissions:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
```

---

### 3.3 Audit Logging (FERPA Requirement)

```python
# src/api/audit.py
import logging
from datetime import datetime
from sqlalchemy import insert

class AuditLogger:
    def __init__(self, db_session):
        self.db = db_session
        self.logger = logging.getLogger("audit")

    async def log_event(
        self,
        event_type: str,
        user_id: str,
        school_id: str,
        action: str,
        details: dict,
        ip_address: str,
    ):
        """Log event to database and CloudWatch"""
        audit_record = {
            "event_type": event_type,
            "user_id": user_id,
            "school_id": school_id,
            "action": action,
            "details": details,
            "ip_address": ip_address,
            "created_at": datetime.utcnow(),
        }

        # Write to database
        await self.db.execute(insert(audit_log).values(**audit_record))
        await self.db.commit()

        # Write to CloudWatch
        self.logger.info(f"AUDIT: {event_type} by {user_id}: {action}")
```

**Audit Events to Log:**
```
✅ User login (timestamp, user_id, IP address)
✅ Query execution (query_text hash, user_id, school_id)
✅ Data access (who accessed what, when)
✅ Data export (user_id, what data, timestamp)
✅ Settings change (who changed what)
✅ Permission grant/revoke
✅ API key rotation
```

---

### 3.4 Data Handling (FERPA MVP Requirements)

#### **MVP (Synthetic Data Only):**
```
No PII: All test data is synthetic
No retention concerns: Can keep indefinitely for testing
No deletion requirements: No real student data
Logging: Can be verbose for debugging
```

#### **Beta/Production (Real Student Data):**

**Data Retention Policy:**
```
Raw Recordings:
- Retain: 30 days (beta QA period)
- Delete: Automatic after 30 days via Lambda
- Cost: ~$2/month for 30 days of recordings

Meeting Summaries:
- Retain: Indefinitely (teachers need for action)
- Access: RBAC-controlled (teacher only sees their team)
- Storage: PostgreSQL (encrypted)

De-Identification Keys:
- Encrypt: AES-256 via AWS KMS
- Delete: Automatic after 90 days via Lambda
- Access: System only (no human access)
```

**Automatic Deletion Lambda:**
```python
# lambda/delete_old_recordings.py
import boto3
from datetime import datetime, timedelta

def lambda_handler(event, context):
    """Delete raw recordings older than 30 days"""
    db = connect_to_rds()

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Find all recordings older than 30 days
    old_recordings = db.query(Recording).filter(
        Recording.created_at < thirty_days_ago
    ).all()

    for recording in old_recordings:
        # Delete from S3
        s3.delete_object(
            Bucket='plc-coach-recordings',
            Key=recording.s3_key
        )
        # Mark as deleted in DB
        recording.deleted_at = datetime.utcnow()
        db.commit()

    return {
        "statusCode": 200,
        "body": f"Deleted {len(old_recordings)} old recordings"
    }

# Schedule: EventBridge rule to run daily at 2 AM UTC
```

---

### 3.5 Data Processing Agreement (DPA) - Beta/Prod

When onboarding real schools in Beta, require schools to sign a DPA that specifies:

```
1. Data Use: "Only for PLC meeting facilitation and quality indicators"
2. Data Security: "AES-256 encryption, RBAC, audit logging"
3. Data Retention: "30-day QA period, then deletion"
4. Data Residency: "us-east-1 AWS region" (or per school requirement)
5. School's Rights:
   - Audit access logs
   - Request data export
   - Request data deletion
   - Terminate agreement with 30 days notice
```

---

## 4. Terraform Infrastructure-as-Code

### 4.1 Directory Structure

```
terraform/
├── main.tf                 # Provider, VPC, security groups
├── compute.tf              # ECS, ALB
├── database.tf             # RDS PostgreSQL
├── cache.tf                # ElastiCache Redis
├── storage.tf              # S3 backups
├── secrets.tf              # AWS Secrets Manager
├── monitoring.tf           # CloudWatch, CloudTrail
├── variables.tf            # Input variables
├── outputs.tf              # Output values
├── terraform.tfvars        # Variable values (NOT committed)
└── environments/
    ├── mvp.tfvars          # MVP config
    ├── alpha.tfvars        # Alpha config
    └── production.tfvars   # Production config
```

### 4.2 Example Terraform Files

**main.tf:**
```hcl
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "plc-coach-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "plc-coach"
      Environment = var.environment
      ManagedBy   = "Terraform"
      CreatedAt   = timestamp()
    }
  }
}

# VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "plc-coach-vpc"
  }
}

# Public Subnets
resource "aws_subnet" "public" {
  count                   = length(var.availability_zones)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = var.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "plc-coach-public-${var.availability_zones[count.index]}"
  }
}

# Private Subnets
resource "aws_subnet" "private" {
  count             = length(var.availability_zones)
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = var.availability_zones[count.index]

  tags = {
    Name = "plc-coach-private-${var.availability_zones[count.index]}"
  }
}

# Security Groups
resource "aws_security_group" "alb" {
  name   = "plc-coach-alb"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "ecs" {
  name   = "plc-coach-ecs"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]  # Allow outbound to OpenAI, Perplexity
  }
}

resource "aws_security_group" "rds" {
  name   = "plc-coach-rds"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
}

resource "aws_security_group" "qdrant" {
  name   = "plc-coach-qdrant"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 6333
    to_port         = 6333
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
}

resource "aws_security_group" "redis" {
  name   = "plc-coach-redis"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
}
```

**compute.tf:**
```hcl
# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "plc-coach-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ECS Task Execution Role (allows pulling images, writing logs)
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "plc-coach-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role (allows accessing secrets, S3, KMS)
resource "aws_iam_role" "ecs_task_role" {
  name = "plc-coach-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_task_role_policy" {
  name = "plc-coach-ecs-task-policy"
  role = aws_iam_role.ecs_task_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
        ]
        Resource = "arn:aws:secretsmanager:*:*:secret:plc-coach/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
        ]
        Resource = "${aws_s3_bucket.backups.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
        ]
        Resource = "*"
      }
    ]
  })
}

# ECS Task Definition
resource "aws_ecs_task_definition" "api" {
  family                   = "plc-coach-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_task_cpu
  memory                   = var.ecs_task_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${var.ecr_repository_url}:${var.image_tag}"
    essential = true
    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
    }]

    environment = [
      {
        name  = "ENVIRONMENT"
        value = var.environment
      },
      {
        name  = "OPENAI_MODEL"
        value = var.openai_model
      },
      {
        name  = "QDRANT_URL"
        value = "http://${aws_instance.qdrant.private_ip}:6333"
      },
      {
        name  = "REDIS_URL"
        value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379"
      },
    ]

    secrets = [
      {
        name      = "OPENAI_API_KEY"
        valueFrom = aws_secretsmanager_secret.openai_api_key.arn
      },
      {
        name      = "DATABASE_URL"
        valueFrom = aws_secretsmanager_secret.database_url.arn
      },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "ecs"
      }
    }
  }])
}

# ECS Service
resource "aws_ecs_service" "api" {
  name            = "plc-coach-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.api,
  ]
}

# Application Load Balancer
resource "aws_lb" "main" {
  name               = "plc-coach-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "plc-coach-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 3
    interval            = 30
    path                = "/api/v1/health"
    matcher             = "200"
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.main.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"
  certificate_arn   = aws_acm_certificate.main.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# Auto-Scaling (Alpha+)
resource "aws_autoscaling_target" "ecs_target" {
  count              = var.environment == "production" ? 1 : 0
  max_capacity       = var.ecs_max_capacity
  min_capacity       = var.ecs_min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_autoscaling_policy" "ecs_policy_cpu" {
  count              = var.environment == "production" ? 1 : 0
  name               = "plc-coach-cpu-autoscaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_autoscaling_target.ecs_target[0].resource_id
  scalable_dimension = aws_autoscaling_target.ecs_target[0].scalable_dimension
  service_namespace  = aws_autoscaling_target.ecs_target[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70.0
  }
}

resource "aws_autoscaling_policy" "ecs_policy_memory" {
  count              = var.environment == "production" ? 1 : 0
  name               = "plc-coach-memory-autoscaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_autoscaling_target.ecs_target[0].resource_id
  scalable_dimension = aws_autoscaling_target.ecs_target[0].scalable_dimension
  service_namespace  = aws_autoscaling_target.ecs_target[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value = 80.0
  }
}
```

**database.tf:**
```hcl
resource "aws_db_subnet_group" "main" {
  name       = "plc-coach-db-subnet"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_rds_cluster" "main" {
  cluster_identifier      = "plc-coach-db"
  engine                  = "aurora-postgresql"
  engine_version          = "15.3"
  database_name           = "plc_coach"
  master_username         = "admin"
  master_password         = random_password.db_password.result
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  skip_final_snapshot     = var.environment == "development" ? true : false
  backup_retention_period = var.backup_retention_days
  storage_encrypted       = true
  kms_key_id              = aws_kms_key.rds.arn

  tags = {
    Name = "plc-coach-db"
  }
}

resource "aws_rds_cluster_instance" "main" {
  count              = var.rds_instance_count
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = var.rds_instance_class
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = false

  monitoring_interval    = 60
  monitoring_role_arn    = aws_iam_role.rds_monitoring.arn
  enable_performance_insights = true

  tags = {
    Name = "plc-coach-db-${count.index + 1}"
  }
}

resource "random_password" "db_password" {
  length  = 32
  special = true
}

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "plc-coach/database-url"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://${aws_rds_cluster.main.master_username}:${random_password.db_password.result}@${aws_rds_cluster.main.endpoint}:5432/${aws_rds_cluster.main.database_name}"
}
```

---

## 5. Deployment Process

### 5.1 MVP Deployment Checklist

```
[ ] AWS Account Setup
    [ ] Create new AWS account
    [ ] Enable CloudTrail
    [ ] Configure billing alerts

[ ] Terraform State
    [ ] Create S3 bucket for terraform state
    [ ] Create DynamoDB table for locks
    [ ] Initialize terraform

[ ] Deploy Infrastructure
    [ ] terraform plan -var-file=environments/mvp.tfvars
    [ ] terraform apply -var-file=environments/mvp.tfvars

[ ] Application Setup
    [ ] Build Docker image
    [ ] Push to ECR
    [ ] Update ECS task definition with image URI

[ ] Database Initialization
    [ ] Run migrations: alembic upgrade head
    [ ] Seed users table (internal team)

[ ] Qdrant Setup
    [ ] Load 25 PLC books
    [ ] Create collection snapshot
    [ ] Test similarity search

[ ] Redis Warm-up
    [ ] Prime cache with common queries (optional)

[ ] Testing
    [ ] Health check: curl https://api.plccoach.internal/health
    [ ] Query test: POST /api/v1/query with test question
    [ ] End-to-end test with team

[ ] Monitoring
    [ ] Set up CloudWatch dashboards
    [ ] Configure alarms for errors, latency
    [ ] Test alarm notifications

[ ] Documentation
    [ ] Document secrets storage
    [ ] Document deployment procedure
    [ ] Document rollback procedure
```

### 5.2 MVP to Alpha Transition Checklist

```
[ ] FERPA Preparation
    [ ] Draft DPA template
    [ ] Update privacy notice
    [ ] Implement RBAC schema in database

[ ] Authentication
    [ ] Implement Google OAuth 2.0
    [ ] Test SSO with team members

[ ] Audit Logging
    [ ] Implement audit log service
    [ ] Connect to CloudWatch
    [ ] Test log queries

[ ] Secrets Rotation
    [ ] Set up automated API key rotation
    [ ] Document rotation procedure

[ ] Backup Testing
    [ ] Test RDS snapshot restoration
    [ ] Test S3 backup restoration
    [ ] Document recovery time objective (RTO)
```

---

## 6. Monitoring & Observability

### 6.1 CloudWatch Dashboards

**Key Metrics:**
```
API Performance:
- Request count (by endpoint, status code)
- P50/P95/P99 latency
- Error rate
- Cache hit ratio

Resource Utilization:
- ECS CPU / Memory
- RDS CPU / Connections
- Redis memory usage
- Qdrant query latency

Business Metrics:
- Queries per user per day
- Top questions asked (anonymized)
- Cost per query
```

### 6.2 Alarms

```
Critical Alerts:
- ECS task failures (restart count > 3/min)
- RDS CPU > 80% for 5 minutes
- API error rate > 5%
- API P99 latency > 5 seconds

Warning Alerts:
- ECS memory > 70%
- Redis memory > 80%
- API error rate > 1%
- Qdrant response time > 1 second

Low-Priority Alerts:
- API P95 latency > 3 seconds
- RDS replication lag > 1 second
```

---

## 7. Cost Estimation

### 7.1 MVP Monthly Cost

```
Compute:
- ECS Fargate (1 task, 1 vCPU, 2 GB): $30
- NAT Gateway: $45 (per month, per AZ)

Database:
- RDS PostgreSQL (db.t3.micro, single-AZ): $15
- Backup storage (7 days): $2

Vector DB:
- Qdrant EC2 (t3.medium): $30
- EBS storage (50 GB): $5

Cache:
- ElastiCache (cache.t3.micro): $10

Storage:
- S3 (minimal): $1

Monitoring:
- CloudWatch Logs: $2-5
- CloudTrail: $2

Total MVP: ~$140-150/month
```

### 7.2 Beta/Production Scaling

```
With 100 concurrent users:
- ECS Fargate (3-5 tasks): $100-150
- RDS (db.t3.small, Multi-AZ): $60
- Qdrant (3 nodes, HA): $300
- ElastiCache (r6g.large, Multi-AZ): $150
- NAT Gateway (2 AZs): $90
- Monitoring & Logs: $50

Total Beta: ~$750-800/month
```

---

## 8. Runbook: Day-1 Operations

### 8.1 Deploying a New Version

```bash
# 1. Build and push new Docker image
docker build -t plc-coach:v1.2.3 .
docker tag plc-coach:v1.2.3 {account}.dkr.ecr.us-east-1.amazonaws.com/plc-coach:v1.2.3
docker push {account}.dkr.ecr.us-east-1.amazonaws.com/plc-coach:v1.2.3

# 2. Update ECS task definition
aws ecs register-task-definition \
  --cli-input-json file://task-definition.json

# 3. Update ECS service with new task definition
aws ecs update-service \
  --cluster plc-coach-cluster \
  --service plc-coach-api \
  --task-definition plc-coach-api:2 \
  --force-new-deployment

# 4. Monitor rollout
aws ecs wait services-stable \
  --cluster plc-coach-cluster \
  --services plc-coach-api

# 5. Run smoke tests
curl https://api.plccoach.internal/api/v1/health
```

### 8.2 Scaling Up for Traffic Spike

```bash
# Increase desired task count
aws ecs update-service \
  --cluster plc-coach-cluster \
  --service plc-coach-api \
  --desired-count 5
```

### 8.3 Responding to Error Spike

```bash
# Check CloudWatch Logs
aws logs tail /ecs/plc-coach-api --follow

# Check ECS task status
aws ecs describe-services --cluster plc-coach-cluster --services plc-coach-api

# If needed, rollback to previous task definition
aws ecs update-service \
  --cluster plc-coach-cluster \
  --service plc-coach-api \
  --task-definition plc-coach-api:1
```

---

## 9. Appendix: Environment Variables

### .env.example (NOT for production)

```bash
# Only for local development with docker-compose
# Production: use AWS Secrets Manager

# OpenAI
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4o
EMBED_MODEL=text-embedding-3-large
EMBED_DIMENSIONS=3072

# Qdrant (Local)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
USE_LOCAL_QDRANT=true

# Redis (Local)
REDIS_URL=redis://localhost:6379

# Database (Local)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/plc_kb

# API
API_KEY=dev-api-key
API_HOST=0.0.0.0
API_PORT=8000

# Perplexity (Alpha+)
PERPLEXITY_API_KEY=

# Environment
ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

### variables.tf (Terraform)

```hcl
variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (development, staging, production)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of AZs"
  default     = ["us-east-1a", "us-east-1b"]
}

variable "ecs_task_cpu" {
  description = "ECS task CPU units"
  default     = 1024  # 1 vCPU for MVP, 2048+ for production
}

variable "ecs_task_memory" {
  description = "ECS task memory in MB"
  default     = 2048  # 2 GB for MVP, 4096+ for production
}

variable "ecs_desired_count" {
  description = "Desired number of ECS tasks"
  default     = 1  # MVP
}

variable "ecs_min_capacity" {
  description = "Minimum ECS tasks for auto-scaling"
  default     = 1
}

variable "ecs_max_capacity" {
  description = "Maximum ECS tasks for auto-scaling"
  default     = 10
}

variable "rds_instance_class" {
  description = "RDS instance class"
  default     = "db.t3.micro"  # MVP
}

variable "rds_instance_count" {
  description = "Number of RDS instances"
  default     = 1  # MVP, 2+ for production
}

variable "backup_retention_days" {
  description = "RDS backup retention"
  default     = 7
}

variable "openai_model" {
  description = "OpenAI model to use"
  default     = "gpt-4o"
}

variable "image_tag" {
  description = "Docker image tag"
  type        = string
}

variable "ecr_repository_url" {
  description = "ECR repository URL"
  type        = string
}
```

---

## 10. Security Checklist (Before Beta)

```
[ ] Network Security
    [ ] VPC configured with public/private subnets
    [ ] Security groups restrict traffic to minimum necessary
    [ ] NACLs configured (optional, SG usually sufficient)
    [ ] VPC Flow Logs enabled for troubleshooting

[ ] Data Encryption
    [ ] EBS encrypted with KMS keys
    [ ] RDS encrypted with KMS keys
    [ ] S3 encrypted with KMS keys
    [ ] Secrets Manager encrypts secrets
    [ ] TLS for all external communication (443)

[ ] Access Control
    [ ] IAM roles follow least-privilege principle
    [ ] No hardcoded credentials in code/containers
    [ ] API key rotation automated
    [ ] SSH access to EC2 disabled (Systems Manager only)

[ ] Audit & Logging
    [ ] CloudTrail enabled (all API calls)
    [ ] VPC Flow Logs enabled
    [ ] RDS query logging enabled
    [ ] Application logs sent to CloudWatch
    [ ] Audit table populated for all user actions

[ ] Compliance
    [ ] DPA template reviewed by legal
    [ ] Data retention policies documented
    [ ] Deletion automation tested
    [ ] Backup/restore tested

[ ] Incident Response
    [ ] Security contacts documented
    [ ] Escalation procedure defined
    [ ] Backup restoration tested
    [ ] Runbook for data breach created
```

---

## 11. Next Steps

1. **Week 1**: Review this document with security/compliance team
2. **Week 2**: Create new AWS account, set up Terraform state backend
3. **Week 3**: Deploy MVP infrastructure with `terraform apply`
4. **Week 4**: Deploy application, test end-to-end
5. **Ongoing**: Monitor, collect feedback, plan Alpha (OAuth, RBAC)

---

**Document Owner**: Infrastructure Team
**Last Updated**: February 18, 2026
**Next Review**: When transitioning to Alpha

