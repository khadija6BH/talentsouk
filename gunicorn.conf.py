"""Single process: background mail/radar worker and persistent file storage."""
import os
bind = "0.0.0.0:" + os.environ.get("PORT", "8000")
workers = 1
worker_class = "gthread"
threads = 4
timeout = 180
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
preload_app = False
