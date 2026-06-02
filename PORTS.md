# Ports

## Published by this stack on `am-ch-01`

| Host port | Bind         | Service     | Why published                                    |
| --------- | ------------ | ----------- | ------------------------------------------------ |
| **3001**  | `0.0.0.0`    | Metabase    | LAN users hit it from browsers                   |
| **8090**  | `127.0.0.1`  | ingest      | Loopback only — operator `/healthz` and `/run`   |

`postgres` is **not** published. Metabase + ingest reach it on the
internal Docker network. For ad-hoc shell access:

```bash
docker exec -it ninja-postgres psql -U ninja -d ninja
```

If you ever genuinely need Postgres published, uncomment the loopback
binding in `docker-compose.yml` (host-only, no LAN exposure).

## Other stuff on `am-ch-01` (snapshot 2026-06-02)

Captured from `ss -tlnp` so we don't reuse ports. Update this when new
stacks land.

| Port            | What                          |
| --------------- | ----------------------------- |
| 22              | SSH                           |
| 1514            | Graylog syslog input          |
| 3000            | Grafana (dmarc stack)         |
| 5044            | Logstash beats input          |
| 6789, 6875      | Bookstack (pasta) / web       |
| 7080, 7180, 7443, 7543 | various                |
| 8000, 8444      | likely Mailcow / similar      |
| 8080, 8081, 8082, 8880, 8881, 8882 | dmarc-manager (8082), parse-dmarc (8081), misc |
| 8999            | unknown app                   |
| 9000, 9001, 9443 | Portainer                    |
| 9090            | Prometheus (dmarc stack)     |
| 9200, 9300, 9543 | Elasticsearch / similar     |
| 10050, 10051, 10060, 10061 | Zabbix agents/server |
| 11002, 11084, 11443 | local discovery / pasta loopback |
| 12201           | Graylog GELF                  |
| 28082           | unknown (pasta)               |

### Free / claimed by us

- **3001** — Metabase (this stack).
- **8090** — ingest, loopback only (this stack).
- 5432 — Postgres (this stack, **not published**).

### Suggested ranges for future stacks here

Big sparse blocks: `3002–3099`, `4xxx`, `6000–6700`, `8100–8400`,
`8500–8800`, anything 11000+. Avoid the 7000s and 9000s — already
crowded.
