# Capacity baseline (observation only)

Collected: 2026-11-19T23:02:33.6484159+08:00
Config: http://portal.127.0.0.1.nip.io:8080 / project harness-local-dev

## Host
- Windows, logical CPUs: 16, RAM: 31.29 GB, C: free: 59.93 GB
- Docker: 
29.9.2
- Docker disk usage:
```
TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
Images          26        16        15.29GB   1.602GB (10%)
Containers      20        14        276.6MB   116.4MB (42%)
Local Volumes   27        21        19.61GB   170.1MB (0%)
Build Cache     28        0         1.222GB   490.5MB
```

## Container snapshot

| Container | CPU% | Memory |
|---|---|---|
| harness-harness-local-dev-rt-37c8fce0-5388-4d5d-bb69-62521ff5dee3-g11 | 0.32% | 309MiB / 1GiB |
| harness-harness-local-dev-rt-00a36e23-182b-4fce-a9cb-86829a3673b2-g2 | 0.30% | 308MiB / 1GiB |
| harness-harness-local-dev-rt-319fc425-cf45-4307-b4a9-b693fe67cad9-g8 | 0.31% | 307.6MiB / 1GiB |
| harness-local-dev-worker-1 | 0.21% | 49.53MiB / 15.27GiB |
| harness-local-dev-api-1 | 0.15% | 70.79MiB / 15.27GiB |
| harness-local-dev-edge-1 | 0.00% | 14.14MiB / 15.27GiB |
| harness-local-dev-relay-1 | 0.10% | 65.34MiB / 15.27GiB |
| harness-local-dev-llm-1 | 0.13% | 69.62MiB / 15.27GiB |

## Model request latency (harness.model_requests)

```
model      | n  | avg_ms | max_ms | tokens 
----------------+----+--------+--------+--------
 deepseek-flash | 45 |   2912 |  20088 | 622243
(1 row)
```

## Notes
- Dev-machine snapshot, not a production capacity guarantee.
- T17 cold/hot start x5 and 1/2/4-space load tests still require a dedicated test environment.
