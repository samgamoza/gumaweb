# generated-sites/

Runtime output of the publishing pipeline when `STORAGE_BACKEND=local` (contents are git-ignored).

```
<subdomain>/                      live site, served by nginx (http://localhost:8080/<subdomain>/)
_releases/<subdomain>/v<version>/ immutable build artifacts (last 3 kept for rollback)
```

In production the same layout lives in an RWX volume or an S3-compatible bucket (MinIO).
