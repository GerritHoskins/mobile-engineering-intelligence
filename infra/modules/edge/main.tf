# HTTPS at the edge on CloudFront's default certificate (no domain needed).
# The API has no authentication yet, so a CloudFront Function admits only the
# allowed IPv4 ranges; the ALB behind it admits only CloudFront (prefix list
# plus a secret header, see modules/service).

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled" # every response is per-request API output
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_function" "ip_allowlist" {
  name    = "${var.name}-ip-allowlist"
  runtime = "cloudfront-js-2.0"
  comment = "Admit only allowed IPv4 ranges (stand-in for real auth in the POC)"
  publish = true
  code = templatefile("${path.module}/ip_allowlist.js.tftpl", {
    allowed = jsonencode(var.allowed_cidrs)
  })
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  comment         = var.name
  price_class     = "PriceClass_100"
  is_ipv6_enabled = false # the allowlist matches IPv4 viewers only

  origin {
    origin_id   = "alb"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only" # the ALB has no certificate (no domain)
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60 # LLM explanations take ~15-20 s
    }

    custom_header {
      name  = var.origin_verify_header
      value = var.origin_verify_secret
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.ip_allowlist.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
