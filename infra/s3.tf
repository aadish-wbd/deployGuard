resource "aws_s3_bucket" "incidents" {
  bucket = "${local.name_prefix}-incidents-${local.account_id}"
}

resource "aws_s3_bucket_versioning" "incidents" {
  bucket = aws_s3_bucket.incidents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "incidents" {
  bucket = aws_s3_bucket.incidents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "incidents" {
  bucket = aws_s3_bucket.incidents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
