# GuardianOps

A self-healing MLOps safety net for a fraud-detection API. Detects both crash failures and *silent* wrong-answer failures, auto-fixes what it can, and holds a human approval gate for the rest. Full audit trail per incident.

Read [DIARY.md](DIARY.md) for a plain-language walk-through of what this project is, why every piece exists, and what to say if a professor asks about it.

## Quick start
```bash
docker compose up --build
```

| Service | URL |
| --- | --- |
| Dashboard | http://localhost:8080 |
| Guardian API | http://localhost:8002/docs |
| Fraud API | http://localhost:8001/docs |
| Chaos Injector | http://localhost:8003/docs |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| MLflow | http://localhost:5000 |
