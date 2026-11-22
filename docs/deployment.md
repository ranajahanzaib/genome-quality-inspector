# Deployment

This release is intended for trusted local use and has no authentication. It must not be exposed as a public multi-user service. The API stores files at `GQI_DATA_DIR`; protect and back up that directory with the database. The database stores the latest analysis JSON document.

For an internal single-user deployment, use HTTPS at a trusted reverse proxy, restrict network access to the API and frontend, use a dedicated PostgreSQL role and secret, set explicit CORS origins, retain backups, and run the RQ worker separately with Redis. Set a conservative upload cap and analysis timeout for the host. Avoid storing sensitive human genomic data without an appropriate privacy and governance review.

Docker Compose supplies PostgreSQL and Redis for local development. The web app, API, and Rust engine run as host processes using the commands in `docs/getting-started.md`. This repository does not provide production container images or a hosted deployment configuration.
