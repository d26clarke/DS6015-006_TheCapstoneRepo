# AWS VPC Setup Guide for the Tree Canopy Project
## SageMaker Unified Studio Domain — Private Subnet Architecture

**Target architecture:** A fully private VPC with two private subnets across two Availability Zones, no internet gateway, and a complete set of VPC endpoints (AWS PrivateLink) so that SageMaker Unified Studio and all supporting services communicate entirely within the AWS network.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  VPC: tree-canopy-vpc  (10.0.0.0/16)                                        │
│  Region: us-east-1                                                          │
│                                                                             │
│  ┌──────────────────────────────┐  ┌──────────────────────────────┐         │
│  │  Private Subnet A            │  │  Private Subnet B            │         │
│  │  10.0.1.0/24                 │  │  10.0.2.0/24                 │         │
│  │  AZ: us-east-1a              │  │  AZ: us-east-1b              │         │
│  │                              │  │                              │         │
│  │  SageMaker ENIs              │  │  SageMaker ENIs              │         │
│  │  VPC Endpoint ENIs           │  │  VPC Endpoint ENIs           │         │
│  └──────────────────────────────┘  └──────────────────────────────┘         │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Private Route Table (shared by both subnets)                       │    │
│  │  Destination: pl-63a5400a (S3 prefix list) → S3 Gateway Endpoint   │    │
│  │  Destination: 10.0.0.0/16 → local                                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  VPC Interface Endpoints (PrivateLink) — one ENI per subnet per endpoint   │
│  VPC Gateway Endpoint — S3 (free, route table entry only)                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Create the VPC

### Step 1.1 — Open the VPC Console

1. Sign in to the AWS Management Console and navigate to **VPC** (search "VPC" in the top search bar).
2. Confirm the region is **us-east-1 (N. Virginia)** in the top-right corner.

### Step 1.2 — Create the VPC

1. In the left navigation pane, click **Your VPCs**, then click **Create VPC**.
2. Select **VPC only** (not "VPC and more" — you will create subnets manually for precise control).
3. Fill in the fields as follows:

| Field | Value | Notes |
| :--- | :--- | :--- |
| **Name tag** | `tree-canopy-vpc` | |
| **IPv4 CIDR block** | `10.0.0.0/16` | Provides 65,536 addresses — sufficient for 5+ years of growth |
| **IPv6 CIDR block** | No IPv6 CIDR block | Not required for this workload |
| **Tenancy** | Default | Use Dedicated only if your organization's compliance policy requires it |

4. Click **Create VPC**.

### Step 1.3 — Enable DNS Support and DNS Hostnames

These two settings are **mandatory** for VPC interface endpoints to resolve correctly via private DNS.

1. On the VPC list page, select `tree-canopy-vpc`.
2. Click **Actions → Edit VPC settings**.
3. Check both **Enable DNS resolution** and **Enable DNS hostnames**.
4. Click **Save**.

> **Why this matters:** Interface endpoints use private hosted zones in Route 53 to override the public DNS names of AWS services (e.g., `sagemaker.us-east-1.amazonaws.com`) with private IP addresses inside your VPC. If DNS hostnames are disabled, this override does not function and all SDK calls will attempt to reach the public internet.

---

## Phase 2 — Create the Private Subnets

### Step 2.1 — Create Private Subnet A (us-east-1a)

1. In the left navigation pane, click **Subnets**, then click **Create subnet**.
2. Select `tree-canopy-vpc` from the **VPC ID** dropdown.
3. Fill in the subnet fields:

| Field | Value |
| :--- | :--- |
| **Subnet name** | `tree-canopy-private-1a` |
| **Availability Zone** | `us-east-1a` |
| **IPv4 CIDR block** | `10.0.1.0/24` |

4. Click **Add new subnet** to add the second subnet in the same creation flow.

### Step 2.2 — Create Private Subnet B (us-east-1b)

In the second subnet block, fill in:

| Field | Value |
| :--- | :--- |
| **Subnet name** | `tree-canopy-private-1b` |
| **Availability Zone** | `us-east-1b` |
| **IPv4 CIDR block** | `10.0.2.0/24` |

5. Click **Create subnet**.

### Step 2.3 — Disable Auto-Assign Public IP on Both Subnets

For each subnet (`tree-canopy-private-1a` and `tree-canopy-private-1b`):

1. Select the subnet from the list.
2. Click **Actions → Edit subnet settings**.
3. Ensure **Enable auto-assign public IPv4 address** is **unchecked**.
4. Click **Save**.

> These are private subnets with no internet gateway. Auto-assigning public IPs would be non-functional and could create a false impression of internet reachability.

---

## Phase 3 — Create the Route Table

A single private route table will be shared by both subnets. It will have no route to an internet gateway; the only additional route added later will be for the S3 Gateway endpoint.

### Step 3.1 — Create the Route Table

1. In the left navigation pane, click **Route tables**, then click **Create route table**.

| Field | Value |
| :--- | :--- |
| **Name** | `tree-canopy-private-rt` |
| **VPC** | `tree-canopy-vpc` |

2. Click **Create route table**.

### Step 3.2 — Associate Both Subnets

1. Select `tree-canopy-private-rt`.
2. Click the **Subnet associations** tab, then **Edit subnet associations**.
3. Check both `tree-canopy-private-1a` and `tree-canopy-private-1b`.
4. Click **Save associations**.

---

## Phase 4 — Create the Security Groups

Two security groups are required: one for the SageMaker domain and notebook instances, and one for the VPC endpoint network interfaces.

### Step 4.1 — SageMaker Security Group

1. In the left navigation pane, click **Security groups**, then **Create security group**.

| Field | Value |
| :--- | :--- |
| **Security group name** | `tree-canopy-sagemaker-sg` |
| **Description** | `SageMaker Unified Studio domain, notebooks, and training jobs` |
| **VPC** | `tree-canopy-vpc` |

2. Under **Inbound rules**, click **Add rule**:

| Type | Protocol | Port range | Source | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| All traffic | All | All | `tree-canopy-sagemaker-sg` (self-referencing) | Allows SageMaker components to communicate with each other |

3. Under **Outbound rules**, the default **All traffic → 0.0.0.0/0** rule is acceptable. In a stricter posture, restrict outbound to TCP 443 toward the VPC endpoint security group.
4. Click **Create security group**.

### Step 4.2 — VPC Endpoint Security Group

1. Create a second security group:

| Field | Value |
| :--- | :--- |
| **Security group name** | `tree-canopy-vpce-sg` |
| **Description** | `Controls TLS traffic to VPC interface endpoints` |
| **VPC** | `tree-canopy-vpc` |

2. Under **Inbound rules**, add:

| Type | Protocol | Port | Source | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| HTTPS | TCP | 443 | `tree-canopy-sagemaker-sg` | Allows SageMaker to reach AWS service endpoints |
| HTTPS | TCP | 443 | `10.0.0.0/16` | Allows any resource in the VPC to reach endpoints |

3. Leave the default outbound rule (all traffic allowed).
4. Click **Create security group**.

---

## Phase 5 — Create the VPC Endpoints

This is the most extensive phase. SageMaker Unified Studio requires a combination of one **Gateway endpoint** (for S3, which is free) and multiple **Interface endpoints** (PrivateLink, which incur an hourly charge per AZ).

All interface endpoints must be created in **both private subnets** to ensure high availability across the two Availability Zones.

### Step 5.1 — S3 Gateway Endpoint (free)

1. In the left navigation pane, click **Endpoints**, then **Create endpoint**.
2. Fill in the fields:

| Field | Value |
| :--- | :--- |
| **Name tag** | `tree-canopy-s3-gateway` |
| **Service category** | AWS services |
| **Service name** | `com.amazonaws.us-east-1.s3` (select the **Gateway** type row) |
| **VPC** | `tree-canopy-vpc` |
| **Route tables** | Check `tree-canopy-private-rt` |
| **Policy** | Full access (or restrict to `arn:aws:s3:::central-virginia-tree-canopy-project` and `arn:aws:s3:::central-virginia-tree-canopy-project/*`) |

3. Click **Create endpoint**.

> A Gateway endpoint does not create ENIs. Instead, it adds a route to your route table that directs S3 traffic through the AWS backbone rather than the internet.

### Step 5.2 — Interface Endpoints (PrivateLink)

For each endpoint in the table below, follow this procedure:

1. Click **Create endpoint**.
2. Set **Service category** to **AWS services**.
3. Search for the service name in the search box.
4. Select the **Interface** type row.
5. Set **VPC** to `tree-canopy-vpc`.
6. Under **Subnets**, check **both** `tree-canopy-private-1a` (us-east-1a) and `tree-canopy-private-1b` (us-east-1b).
7. Set **Enable DNS name** to **enabled** (this is the default and is required).
8. Under **Security groups**, select `tree-canopy-vpce-sg`.
9. Click **Create endpoint**.

Repeat for each of the following services:

| # | Name Tag | Service Name | Required? | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `tree-canopy-sagemaker-api` | `com.amazonaws.us-east-1.sagemaker.api` | **Mandatory** | SageMaker control plane — CreateDomain, CreateNotebookInstance, etc. |
| 2 | `tree-canopy-sagemaker-runtime` | `com.amazonaws.us-east-1.sagemaker.runtime` | **Mandatory** | SageMaker inference runtime (InvokeEndpoint) |
| 3 | `tree-canopy-sagemaker-notebook` | `aws.sagemaker.us-east-1.notebook` | **Mandatory** | Notebook instance presigned URL access |
| 4 | `tree-canopy-datazone` | `com.amazonaws.us-east-1.datazone` | **Mandatory** | Amazon DataZone — the underlying service for Unified Studio domains |
| 5 | `tree-canopy-sts` | `com.amazonaws.us-east-1.sts` | **Mandatory** | AWS Security Token Service — role assumption and temporary credentials |
| 6 | `tree-canopy-glue` | `com.amazonaws.us-east-1.glue` | **Mandatory** | AWS Glue — data catalog and ETL jobs used by Unified Studio |
| 7 | `tree-canopy-secretsmanager` | `com.amazonaws.us-east-1.secretsmanager` | **Mandatory** | Secrets Manager — stores domain credentials and connection strings |
| 8 | `tree-canopy-kms` | `com.amazonaws.us-east-1.kms` | **Mandatory** | AWS KMS — encryption of EBS volumes, S3 objects, and secrets |
| 9 | `tree-canopy-ec2` | `com.amazonaws.us-east-1.ec2` | **Mandatory** | EC2 API — required for SageMaker to provision underlying instances |
| 10 | `tree-canopy-ssm` | `com.amazonaws.us-east-1.ssm` | **Mandatory** | Systems Manager — used by SageMaker for instance management |
| 11 | `tree-canopy-cloudwatch-monitoring` | `com.amazonaws.us-east-1.monitoring` | **Mandatory** | CloudWatch Metrics — notebook and training job metrics |
| 12 | `tree-canopy-cloudwatch-logs` | `com.amazonaws.us-east-1.logs` | **Mandatory** | CloudWatch Logs — notebook output and pipeline logs |
| 13 | `tree-canopy-ecr-api` | `com.amazonaws.us-east-1.ecr.api` | **Mandatory** | ECR API — SageMaker pulls container image metadata from ECR |
| 14 | `tree-canopy-ecr-dkr` | `com.amazonaws.us-east-1.ecr.dkr` | **Mandatory** | ECR Docker — SageMaker pulls container images for kernels and jobs |
| 15 | `tree-canopy-athena` | `com.amazonaws.us-east-1.athena` | Recommended | Athena — SQL queries over S3 data from Unified Studio |

> **Cost note:** Each interface endpoint is billed at approximately $0.01/hour per AZ. With 14 interface endpoints across 2 AZs, the estimated cost is approximately **$0.28/hour (~$201/month)** in addition to data processing charges. The S3 Gateway endpoint (endpoint #0) is free.

---

## Phase 6 — Provision the SageMaker Unified Studio Domain

With the VPC infrastructure in place, you can now create the SageMaker Unified Studio domain and attach it to the private subnets.

### Step 6.1 — Open SageMaker Unified Studio

1. In the AWS Console search bar, type **SageMaker Unified Studio** and select it.
2. Click **Create domain**.

### Step 6.2 — Domain Settings

| Field | Value |
| :--- | :--- |
| **Domain name** | `tree-canopy-domain` |
| **Execution role** | `TreeCanopyPipelineRole` |
| **Authentication** | IAM Identity Center (recommended) or IAM |

### Step 6.3 — Network Settings

1. Under **Network and storage**, select **VPC**.
2. Set **VPC** to `tree-canopy-vpc`.
3. Under **Subnets**, select both `tree-canopy-private-1a` and `tree-canopy-private-1b`.
4. Under **Security groups**, select `tree-canopy-sagemaker-sg`.
5. Set **App network access type** to **VPC only** (this disables all public internet access to the domain).

### Step 6.4 — Submit

Click **Submit**. Domain provisioning takes approximately 10–15 minutes. The status will progress from **Creating** to **InService**.

---

## Phase 7 — Verification

Once the domain is **InService**, verify that the private network is functioning correctly.

### Step 7.1 — Verify Endpoint Status

1. Navigate to **VPC → Endpoints**.
2. Confirm all 15 endpoints show a status of **Available**.
3. Any endpoint showing **Pending** will resolve within a few minutes; **Failed** indicates a configuration error (most commonly a missing subnet association or incorrect security group).

### Step 7.2 — Verify S3 Access from a Notebook

Open a SageMaker notebook in the domain and run:

```python
import boto3

s3 = boto3.client('s3', region_name='us-east-1')
response = s3.list_objects_v2(
    Bucket='central-virginia-tree-canopy-project',
    MaxKeys=5
)
print(response.get('Contents', 'Bucket accessible but empty'))
```

A successful response confirms that the S3 Gateway endpoint and `TreeCanopyPipelineRole` are both working correctly.

### Step 7.3 — Confirm Private DNS Resolution

From a notebook terminal, run:

```bash
nslookup sagemaker.us-east-1.amazonaws.com
```

The response should return a **10.0.x.x** IP address (within your VPC CIDR), not a public IP. A public IP (e.g., `52.x.x.x`) indicates that private DNS on the endpoint is not enabled or DNS hostnames are disabled on the VPC.

---

## Quick Reference: Resource Naming Summary

| Resource | Name | CIDR / Value |
| :--- | :--- | :--- |
| VPC | `tree-canopy-vpc` | `10.0.0.0/16` |
| Private Subnet A | `tree-canopy-private-1a` | `10.0.1.0/24` (us-east-1a) |
| Private Subnet B | `tree-canopy-private-1b` | `10.0.2.0/24` (us-east-1b) |
| Route Table | `tree-canopy-private-rt` | — |
| SageMaker SG | `tree-canopy-sagemaker-sg` | Self-referencing inbound |
| Endpoint SG | `tree-canopy-vpce-sg` | TCP 443 inbound from SageMaker SG |
| S3 Gateway Endpoint | `tree-canopy-s3-gateway` | Gateway type (free) |
| Interface Endpoints | `tree-canopy-<service>` | 14 endpoints × 2 AZs |
| Unified Studio Domain | `tree-canopy-domain` | VPC only mode |

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
| :--- | :--- | :--- |
| Domain stuck in **Creating** | Missing mandatory VPC endpoint (DataZone or STS) | Verify all 15 endpoints are in **Available** state |
| `nslookup` returns public IP | Private DNS not enabled on endpoint, or DNS hostnames disabled on VPC | Re-check Phase 1, Step 1.3 and Phase 5, Step 5.2 (Enable DNS name) |
| `AccessDenied` on S3 | S3 Gateway endpoint policy too restrictive, or missing S3 policy on `TreeCanopyPipelineRole` | Verify endpoint policy allows the bucket ARN; re-check IAM role |
| Notebook cannot reach ECR | ECR API or ECR DKR endpoint missing | Create both `ecr.api` and `ecr.dkr` interface endpoints |
| SageMaker domain shows **Failed** | Security group does not allow self-referencing inbound traffic | Re-check `tree-canopy-sagemaker-sg` inbound rule in Phase 4, Step 4.1 |
