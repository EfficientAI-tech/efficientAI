---
id: s3-storage
title: S3 Storage
sidebar_position: 2
---

# S3 Cloud Storage

## Overview

EfficientAI can store audio files and recordings in Amazon S3 or any S3-compatible storage service (MinIO, DigitalOcean Spaces, etc.).

This is useful for:
- Storing large audio files in the cloud
- Scaling storage independently from your server
- Integrating with existing cloud infrastructure

---

## Configuration

### 1. Update config.yml

Add the S3 configuration section to your `config.yml`:

```yaml
s3:
  enabled: true
  bucket_name: "your-bucket-name"
  region: "us-east-1"
  access_key_id: "AKIAIOSFODNN7EXAMPLE"
  secret_access_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
  endpoint_url: null  # Optional: for S3-compatible services
  prefix: "audio/"    # Optional: folder prefix for files
```

### 2. Configuration Options

| Option | Required | Description |
|--------|----------|-------------|
| `enabled` | Yes | Set to `true` to enable S3 storage |
| `bucket_name` | Yes | Name of your S3 bucket |
| `region` | Yes | AWS region (e.g., `us-east-1`, `eu-west-1`) |
| `access_key_id` | Yes | AWS Access Key ID |
| `secret_access_key` | Yes | AWS Secret Access Key |
| `endpoint_url` | No | Custom endpoint for S3-compatible services |
| `prefix` | No | Folder prefix for uploaded files (default: `audio/`) |

---

## AWS Setup

### 1. Create an S3 Bucket

```bash
aws s3 mb s3://your-bucket-name --region us-east-1
```

### 2. Create an IAM User

Create a user with programmatic access and attach this policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name",
        "arn:aws:s3:::your-bucket-name/*"
      ]
    }
  ]
}
```

### 3. Get Credentials

After creating the IAM user, note the **Access Key ID** and **Secret Access Key**.

---

## S3-Compatible Services

### MinIO

```yaml
s3:
  enabled: true
  bucket_name: "efficientai"
  region: "us-east-1"
  access_key_id: "minioadmin"
  secret_access_key: "minioadmin"
  endpoint_url: "http://localhost:9000"
  prefix: "audio/"
```

### DigitalOcean Spaces

```yaml
s3:
  enabled: true
  bucket_name: "your-space-name"
  region: "nyc3"
  access_key_id: "your-spaces-key"
  secret_access_key: "your-spaces-secret"
  endpoint_url: "https://nyc3.digitaloceanspaces.com"
  prefix: "audio/"
```

### Cloudflare R2

```yaml
s3:
  enabled: true
  bucket_name: "your-bucket"
  region: "auto"
  access_key_id: "your-r2-access-key"
  secret_access_key: "your-r2-secret-key"
  endpoint_url: "https://<account-id>.r2.cloudflarestorage.com"
  prefix: "audio/"
```

---

## Verifying Connection

After configuring S3, restart the application:

```bash
eai start-all --config config.yml
```

Upload a test file through the UI or API. Check your S3 bucket to confirm the file appears under the configured prefix.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Access Denied` | Check IAM permissions and bucket policy |
| `NoSuchBucket` | Verify bucket name and region |
| `Connection refused` | Check endpoint_url for S3-compatible services |
| `Invalid credentials` | Verify access_key_id and secret_access_key |
