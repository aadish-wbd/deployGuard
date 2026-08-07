# DeployGuard HTTPS edge (CloudFront)

Use this stack when the DeployGuard ALB is in a **different AWS account** than your Route 53 hosted zone and ACM certificate.

It creates:

- CloudFront distribution (HTTPS termination, no caching for API traffic)
- Route 53 A/AAAA alias records for your custom domain

## Quick start

```bash
cd infra/edge
cp terraform.tfvars.example terraform.tfvars
# Set domain_name, route53_zone_id, origin_dns_name, acm_certificate_arn

terraform init
terraform apply
terraform output public_base_url
```

## Current deployment

| Setting | Value |
|---|---|
| Domain | `deployguard.cmp.wbdisc.com` |
| Origin | `deployguard-dev-alb-1213203056.us-east-1.elb.amazonaws.com` |
| Certificate | `*.cmp.wbdisc.com` (ACM us-east-1) |

Example URLs:

- Health: `https://deployguard.cmp.wbdisc.com/health`
- Investigate: `https://deployguard.cmp.wbdisc.com/api/v1/investigate`
- Databricks webhook: `https://deployguard.cmp.wbdisc.com/api/v1/databricks/webhook`
