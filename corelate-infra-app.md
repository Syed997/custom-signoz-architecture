# How to Correlate App and Infrastructure Data in SigNoz

SigNoz correlates data by matching **resource attributes** that appear in both app telemetry (traces, logs) and infra telemetry (metrics). If both sides carry the same attributes with the same values, SigNoz can link them — letting you click a trace and jump to the pod's metrics, or see which node a slow request ran on.

---

## The Attributes That Enable Correlation

These are the key attributes SigNoz looks for to join app and infra data:

| Attribute | Example Value | What it links |
|---|---|---|
| `k8s.cluster.name` | `test-cluster` | App traces ↔ Cluster metrics |
| `k8s.namespace.name` | `default` | App traces ↔ Namespace metrics |
| `k8s.pod.name` | `laravel-app-6d4f9b` | App traces ↔ Pod metrics |
| `k8s.node.name` | `minikube` | App traces ↔ Node metrics |
| `k8s.deployment.name` | `laravel-app` | App traces ↔ Deployment metrics |
| `deployment.environment` | `minikube-env` | App traces ↔ Infra by environment |
| `service.name` | `laravel` | Traces ↔ Logs (same service) |
| `trace_id` / `span_id` | auto-injected | Traces ↔ Logs (same request) |

---

## What Correlates Automatically (No Extra Work)

### Traces ↔ Logs
If the app uses OpenTelemetry, `trace_id` and `span_id` are automatically injected into logs. SigNoz uses these to link a log line to the exact trace/span it belongs to.

**Requirement:** OTel SDK must be configured with a log exporter (already done in your `.env` with `OTEL_LOGS_EXPORTER=otlp`).

---

## Approach 1: App-Side Resource Attributes (Recommended for external collector)

The app tags its own spans/logs with K8s identity before sending to the collector. SigNoz matches these against infra metrics that carry the same attributes.

### How

Add to your K8s deployment manifest under `env:`:

```yaml
# Step 1: Read pod identity from K8s (Downward API)
- name: K8S_POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: K8S_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
- name: K8S_NODE_NAME
  valueFrom:
    fieldRef:
      fieldPath: spec.nodeName

# Step 2: Pass K8s identity to OTel SDK as resource attributes
- name: OTEL_RESOURCE_ATTRIBUTES
  value: "k8s.pod.name=$(K8S_POD_NAME),k8s.namespace.name=$(K8S_NAMESPACE),k8s.node.name=$(K8S_NODE_NAME),k8s.cluster.name=test-cluster,deployment.environment=minikube-env"

# Step 3: Override collector endpoint — .env uses host.docker.internal (local/Docker only)
#         In K8s use host.minikube.internal (or your collector's actual IP/hostname)
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: "http://host.minikube.internal:4317"
- name: OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
  value: "http://host.minikube.internal:4317/v1/traces"
- name: OTEL_EXPORTER_OTLP_LOGS_ENDPOINT
  value: "http://host.minikube.internal:4317/v1/logs"
```

> **Why override here?** The app's `.env` has `host.docker.internal` which only resolves inside Docker (local dev). When running in K8s, that hostname is unknown — the pod can't find the collector. The deployment manifest env vars take precedence over `.env`, so setting them here fixes it without touching the image.

### Pros
- Works even when the OTel collector is **outside** the K8s cluster
- `k8s.cluster.name` can be explicitly set (processor cannot do this automatically)
- No special K8s RBAC permissions needed

### Cons
- Must be added to every app's deployment manifest individually
- Pod name is dynamic — relies on K8s Downward API interpolation (`$(VAR)` syntax)

---

## Approach 2: `k8sattributes` Processor in OTel Collector (Collector inside cluster only)

The collector intercepts incoming spans/logs, looks up the source pod in the K8s API, and enriches them with K8s attributes automatically. The app sends nothing extra.

### How

Add to your OTel collector config:

```yaml
processors:
  k8sattributes:
    auth_type: serviceAccount
    extract:
      metadata:
        - k8s.pod.name
        - k8s.namespace.name
        - k8s.node.name
        - k8s.deployment.name
  # k8sattributes cannot get cluster name — add it manually
  resource:
    attributes:
      - key: k8s.cluster.name
        value: "test-cluster"
        action: insert
      - key: deployment.environment
        value: "minikube-env"
        action: insert

pipelines:
  traces:
    processors: [k8sattributes, resource, batch]
```

Also requires a K8s ServiceAccount with API read permissions:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: otel-collector
rules:
  - apiGroups: [""]
    resources: ["pods", "namespaces", "nodes"]
    verbs: ["get", "list", "watch"]
```

### Pros
- Zero changes needed in app deployment manifests
- Works across all apps automatically
- Good for environments with many services

### Cons
- Collector **must be inside the K8s cluster** (DaemonSet or Deployment)
- Requires RBAC setup (ClusterRole + ServiceAccount)
- `k8s.cluster.name` must still be added via `resource` processor manually

---

## Approach 3: `resource` Processor Only (Minimal setup, partial correlation)

If you only need cluster/environment-level correlation (not pod-level), you can skip `k8sattributes` and just use the `resource` processor to stamp every span with the cluster name and environment.

### How

```yaml
processors:
  resource:
    attributes:
      - key: k8s.cluster.name
        value: "test-cluster"
        action: insert
      - key: deployment.environment
        value: "minikube-env"
        action: insert
```

### Pros
- Works with collector inside or outside the cluster
- No RBAC setup needed
- Simple config

### Cons
- No pod-level or node-level correlation — you can't drill down to "which pod had this trace"
- All spans from all pods get the same attributes (no per-pod identity)

---

## Approach 4: Combined (Most Complete)

Use **Approach 1** (app-side Downward API) for pod/node-level identity, and **Approach 3** (`resource` processor) as a safety net to ensure cluster name is always present even if the app env var is misconfigured.

```yaml
processors:
  resource:
    attributes:
      - key: k8s.cluster.name
        value: "test-cluster"
        action: upsert   # overwrite if wrong, insert if missing
      - key: deployment.environment
        value: "minikube-env"
        action: upsert
```

This is the most robust setup for an **external collector** architecture.

---

## Your Current Architecture

```
Laravel App (K8s)
    │
    │  spans carry: k8s.pod.name, k8s.namespace.name,
    │               k8s.node.name, k8s.cluster.name=test-cluster
    ▼
OTel Collector (external server)
    │
    ▼
Kafka
    │
    ▼
Kafka Bridge → SigNoz
```

```
K8s Infra (metrics via override-values-prod-infra.yaml)
    │
    │  metrics carry: k8s.cluster.name=test-cluster,
    │                 k8s.pod.name, k8s.node.name, etc.
    ▼
OTel Collector (external server)
    │
    ▼
Kafka → SigNoz
```

SigNoz joins the two streams on matching attributes — primarily `k8s.cluster.name`, `k8s.pod.name`, and `k8s.namespace.name`.

### What you have configured (Approach 1 + partially 4)

- **[laravel-deployment.yaml](experiments/laravel/laravel-otel-instrument/laravel-deployment.yaml)** — Downward API + `OTEL_RESOURCE_ATTRIBUTES` ✓
- **[override-values-prod-infra.yaml](override-values-prod-infra.yaml)** — `clusterName: test-cluster` ✓

### Recommended addition (Approach 4)

Add a `resource` processor in your OTel collector config as a safety net to ensure `k8s.cluster.name` is always stamped on all telemetry.

---

## Summary: Which Approach for Which Architecture

| Scenario | Recommended Approach |
|---|---|
| Collector **outside** cluster (your setup) | Approach 1 + Approach 3 as safety net |
| Collector **inside** cluster (DaemonSet) | Approach 2 + `resource` processor for cluster name |
| Multiple apps, don't want to touch each manifest | Approach 2 (collector inside cluster) |
| Only need environment/cluster-level grouping | Approach 3 alone |
| Maximum correlation (pod + node + cluster) | Approach 1 + 3 combined |
