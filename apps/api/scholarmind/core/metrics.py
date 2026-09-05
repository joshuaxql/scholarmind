from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "scholarmind_http_requests_total",
    "HTTP requests completed by the API",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION = Histogram(
    "scholarmind_http_request_duration_seconds",
    "HTTP request latency",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 15, 60),
)
HTTP_IN_PROGRESS = Gauge(
    "scholarmind_http_requests_in_progress",
    "HTTP requests currently being served",
    ("method",),
)
INGESTION_JOBS = Counter(
    "scholarmind_ingestion_jobs_total",
    "Ingestion job terminal outcomes",
    ("result", "error_code"),
)
INGESTION_DURATION = Histogram(
    "scholarmind_ingestion_duration_seconds",
    "End-to-end paper ingestion latency",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900),
)
INGESTION_TRANSITIONS = Counter(
    "scholarmind_ingestion_stage_transitions_total",
    "Ingestion stage transitions",
    ("stage",),
)
CHAT_GENERATIONS = Counter(
    "scholarmind_chat_generations_total",
    "Chat generation outcomes",
    ("result",),
)
CHAT_DURATION = Histogram(
    "scholarmind_chat_generation_duration_seconds",
    "Chat streaming duration",
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)
RETRIEVAL_FALLBACKS = Counter(
    "scholarmind_retrieval_fallback_total",
    "Qdrant retrieval attempts that fell back to the database",
    ("reason",),
)
RETENTION_DELETIONS = Counter(
    "scholarmind_retention_deletions_total",
    "Papers removed by the retention job",
    ("result",),
)
