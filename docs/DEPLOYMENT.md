# Hosting setup

The code is ready for owner-configured hosting. Public reachability and the release
remain unverified until the owner completes the account and DNS steps below. Keep
the hosting branch on `app` until the live release checks pass. Never put credentials
in this document, build logs, chat, Git, or any browser-prefixed environment variable.

## 1. Identify the Netlify site

In the owner's Netlify account, open the existing project assigned to
`themiddlewatch.com`. Record its exact site slug (the part before `.netlify.app`).
Reuse that project when possible so the existing domain assignment is preserved.
If there is no project, the owner may create one with a chosen slug, stopping if a
payment method or paid option is required. The slug will become `NETLIFY_SITE_NAME`
in Render. Do not publish the frontend until its API origin is configured.

## 2. Create the Neon database

In the owner's Neon account, create a project/database near the Render service's
region. Use a no-cost plan only if available without entering payment details.
Open **Connect**, choose the application database and role, and copy the connection
URI directly into Render's secret `DATABASE_URL` field in the next step. Retain its
TLS query options. A direct connection is sufficient for this single-instance demo;
no database URI belongs in the frontend or in a command pasted into a terminal.

## 3. Create the Render API

In Render choose **New > Blueprint**, authorize access to this repository, select
branch `app`, and use the root `render.yaml`. Review one Python web service on the
free plan. No Render database, paid job or disk is declared. Stop if the dashboard
requires payment. Supply `DATABASE_URL` from Neon and `NETLIFY_SITE_NAME` from step 1
when prompted. Leave all optional model/email values absent.

The build installs `api/requirements.txt`. Startup runs `python -m api.deploy`, which
applies Alembic migrations before opening the port supplied by Render. A failed
migration prevents startup without printing connection details. Hosted SQLite is
rejected. One worker serves requests; cleanup runs every five minutes while awake.

Record the actual HTTPS Render origin once healthy. Visit its `/health` endpoint;
expect `status: ok`, `version: 2.0.0`, and `db: ok`. Do not guess the hostname from the
service name. A free service may sleep, so include the wake-up experience in live
verification. `autoDeployTrigger: checksPass` limits automatic updates to passing CI.

## 4. Connect and build the Netlify frontend

In the project from step 1, connect the GitHub repository and choose branch `app` as
the production branch for this pre-release setup. The root `netlify.toml` specifies:

| Setting | Value |
|---|---|
| Base directory | `web` |
| Build command | `npm run build` |
| Publish directory | `dist` relative to `web` |
| Node version | `22` |
| Public build variable | `VITE_API_URL`: actual Render HTTPS origin, no trailing slash |

Set `VITE_API_URL` for production and deploy-preview build contexts. Trigger a build.
The environment guard intentionally fails Netlify builds without a valid HTTPS API
origin. Variable changes require a new build. Keep database and service keys entirely
out of Netlify. Check the `.netlify.app` URL, refresh a nested URL, and load a sample.
The SPA fallback serves `index.html` while preserving existing asset files.

If the site slug changes, update Render's `NETLIFY_SITE_NAME` and redeploy the API.
Only that site and its previews are allowed, alongside the project domains and local
development origins. Never enable a wildcard CORS origin.

## 5. Assign the domain and HTTPS

In Netlify **Domain management**, confirm `themiddlewatch.com` and
`www.themiddlewatch.com` belong to this project. If already assigned with working DNS,
preserve those records. Otherwise use **Pending DNS verification** to obtain the
project-specific records and apply only the required apex/`www` changes at the DNS
provider. Preserve unrelated records, especially mail records. Complete Netlify's
DNS verification and certificate provisioning, then confirm HTTPS and the preferred
domain redirect. Use the Render origin for the API; an API custom domain is optional.

## 6. Live verification and release

Provide only the public web/API origins to the builder. Before changing `main` or
creating `v2.0.0`, verify:

1. Both public pages and `/health` load over HTTPS, including a cold API wake-up.
2. A real browser sample run, invalid number, CSV, filtering and detail evidence work
   from the custom web domain and an owned preview; unrelated origins are rejected.
3. The simulated-feed banner, mobile controls and keyboard flow remain visible.
4. The run limit holds while forged forwarded headers rotate; independent real
   clients do not share one proxy bucket. The Render-only private-proxy attribution
   is a hosting assumption that must pass this live check.
5. `scripts/evaluate_http.py --url ACTUAL_API_ORIGIN` matches every P0 accuracy field
   for the controlled synthetic benchmark. Never point this script at another API.
6. CI is green for the release commit. Merge `app` into `main` without rewriting
   history, create the `v2.0.0` tag and release notes, and switch hosting branches to
   `main` only after release checks. Until then `main` remains unchanged.

If an account operation, credential or payment is required, the owner performs it.
Optional explanation/email services can remain disabled indefinitely. Enabling them
requires owner-managed keys, a chosen supported model or verified email sender,
and reviewed spending controls; the public demo does not depend on them.

## References

- [Render Blueprint specification and validation](https://render.com/docs/blueprint-spec)
- [Render deploy stages](https://render.com/docs/deploys): separate pre-deploy commands
  require paid services, so this configuration migrates during startup.
- [Neon connection guidance](https://neon.com/docs/connect/connection-errors)
- [Netlify monorepo configuration](https://docs.netlify.com/build/configure-builds/monorepos/)
- [Netlify SPA rewrites](https://docs.netlify.com/manage/routing/redirects/rewrites-proxies/)
- [Netlify external DNS](https://docs.netlify.com/manage/domains/configure-domains/configure-external-dns/)
