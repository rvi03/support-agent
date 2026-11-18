
## Platform probe 2026-11-19 00:34 (CP2.4, A30, D64)

| Phase | Colima used / total MB | Swap used MB | Swap-outs | Swap-ins |
|---|---|---|---|---|
| idle after make up | 3938 / 7921 | 4501 | 977420 | 630883 |
| after one call per alias | 3945 / 7921 | 4501 | 977420 | 630939 |

| Alias | Job check | Seconds | Tokens in / out | Est. cost USD |
|---|---|---|---|---|
| embed | 768 numbers | 0.5 | 18 / 0 | 0.000000 |
| agent | valid JSON {"route": "HANDOFF", "device": "receipt printer"} | 3.7 | 85 / 116 | 0.000067 |
| moderation | label forbidden | 1.5 | 74 / 60 | 0.000037 |
| judge | answered (73 chars) | 1.9 | 19 / 19 | 0.000114 |
| simulator | answered (92 chars) | 1.0 | 19 / 23 | 0.000033 |

Containers at the end:

```
servewell-litellm-1 601MiB / 1GiB
servewell-keycloak-1 499.8MiB / 1GiB
servewell-langfuse-web-1 687.3MiB / 1.5GiB
servewell-langfuse-worker-1 406.4MiB / 1GiB
servewell-prometheus-1 47.99MiB / 512MiB
servewell-clickhouse-1 862MiB / 1.5GiB
servewell-grafana-1 272.7MiB / 512MiB
servewell-valkey-1 6.91MiB / 256MiB
servewell-opa-1 16.44MiB / 256MiB
servewell-seaweedfs-1 71.16MiB / 512MiB
servewell-postgres-1 124.8MiB / 1GiB
```

**PASS: every alias passed; no new swap-outs and no growth in swap used.**
