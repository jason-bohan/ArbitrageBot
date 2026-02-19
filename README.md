# ArbitrageBot

## CI and SonarCloud

This repository includes a GitHub Actions workflow at `.github/workflows/ci.yml` which runs tests and will run a SonarCloud scan if the `SONAR_TOKEN` secret is set in the repository.

To avoid Sonar reporting issues from third-party packages, we exclude virtual environments and `site-packages` from analysis via `sonar-project.properties` at the repo root.

Setup steps for SonarCloud (quick):

- Create a SonarCloud project and get a token.
- In GitHub, go to the repository Settings → Secrets and variables → Actions → New repository secret and add `SONAR_TOKEN` with the token value.
- Optionally set additional Sonar properties (organization) in the GitHub Action or in `sonar-project.properties`.

Run CI locally (optional): install `act` and run the `test` job to validate tests run in the workflow.

Example (install act):

```bash
# macOS / Linux
brew install act || true

# Run tests job
act -j test
```
