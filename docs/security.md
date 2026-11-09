# Security model

PulseForge is self-hosted software, not a managed monitoring service. Operators are responsible for deployment access, target permission, and outbound egress.

## Secure deployment checklist

1. Keep the default Compose port mapping to `127.0.0.1` unless you are operating a properly secured TLS reverse proxy.
2. Set `ADMIN_TOKEN` to a long cryptographically random string for deployments reachable by other people. Example: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
3. Put a TLS reverse proxy or ingress in front of the app; never send the key over a cleartext public connection. The dashboard's access key is saved in the tab's `sessionStorage`, not cookies or persistent browser storage.
4. Do not expose SQLite files or `.env` files. The Docker image runs as an unprivileged user and the database is persisted in a Docker volume.
5. Restrict outbound egress and block cloud metadata endpoints and internal networks at the container/cloud network level. URL validation is best-effort and vulnerable to a DNS rebinding race unless backed by network controls.
6. Keep `ALLOW_PRIVATE_TARGETS=false` for services where untrusted users may influence monitor targets. Enable only on trusted systems where monitoring internal applications is explicitly intended.
7. Treat `ALERT_WEBHOOK_URL` as a secret if the destination URL contains a credential. Do not commit a live webhook endpoint.
8. Avoid storing access tokens in URLs and don't configure targets you do not own or have permission to monitor.
9. Outbox payloads can contain configured URLs and incident error messages; protect and back up the SQLite volume accordingly.
10. The `/docs` and static frontend are publicly readable if you expose the app. API data and metrics endpoints require `X-API-Key` when configured.
11. One application worker and one Kubernetes replica are required for the bundled SQLite scheduler design. Back up the SQLite volume before upgrades.

## What is and isn't protected

- Target URLs must use `http` or `https`; embedded credentials are rejected. Only `GET` and `HEAD` requests are supported. Outbound redirects are never followed.
- By default, target hostnames must resolve exclusively to globally routable addresses and the request does not honor proxy environment variables.
- A preflight DNS lookup cannot guarantee the later HTTP client connects to the same IP. Deploy behind strict egress policy if you accept monitoring targets from partially trusted users.
- Mutations are not individually authorized by role. An `ADMIN_TOKEN` holder is effectively an administrator.
- Access tokens are not logged or embedded in generated documentation. Requests need the custom `X-API-Key` header when protection is enabled.
- No CSRF tokens are required because authentication uses an explicit header, not cookies.
- Webhook events use a local outbox for retry, but there is no built-in audit log of configuration modifications. Retry attempts are at least once; receiving systems should handle duplicate events.

## Kubernetes manifest

The example `k8s/all.yaml` requires an image pushed to your registry and a secret. Before applying, replace the image and create a secret in the target namespace:

```bash
kubectl create secret generic pulseforge-secrets \
  --from-literal=admin-token="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

kubectl apply -f k8s/all.yaml
kubectl port-forward svc/pulseforge 8000:80
```

The Pod runs with `runAsUser: 999`. Make sure the PersistentVolume allows writes by UID 999 (e.g., via a storage class / filesystem ownership arrangement), or the application will fail to create its database. The manifest intentionally doesn't expose an external Ingress.
