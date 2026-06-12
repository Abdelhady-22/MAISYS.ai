# tests/ — Cross-Service Tests

This folder is for tests that span multiple services. Per-service unit tests live inside `services/<service-name>/tests/`.

## Folder Structure

```
tests/
├── integration/                   Tests that exercise 2+ services via HTTP
│   ├── auth_to_chatbot/
│   ├── drug_lookup_flow/
│   └── ...
└── e2e/                           End-to-end user journeys via Playwright (frontend → backend)
    ├── login_flow.spec.ts
    ├── drug_interaction_flow.spec.ts
    └── ...
```

## Integration Tests

Run against `docker-compose up` infrastructure (Postgres, Redis, Qdrant, RabbitMQ) plus all relevant service containers. Test real HTTP requests between services.

Pattern:

```python
async def test_drug_interaction_with_auth(client: AsyncClient, auth_token: str):
    response = await client.post(
        "/api/v1/drug/interactions",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"drug_a": "warfarin", "drug_b": "aspirin"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["severity"] in ("major", "moderate")
    assert len(body["data"]["citations"]) > 0
```

## E2E Tests (Playwright)

Test full user journeys through the frontend. Run against a fully-deployed staging environment, not local Docker.

Pattern:

```typescript
test('drug interaction journey', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /login/i }).click();
  // ... full user flow
  await expect(page.getByText(/major interaction/i)).toBeVisible();
});
```

## CI Wiring

- Pre-commit & feature branch: unit tests only (fast)
- PR to `dev`: unit + integration
- Merge to `dev`: full integration + smoke e2e
- Merge to `stage`: full integration + full e2e against staging
- Merge to `main`: full integration + full e2e + load tests

## Rules

1. **No flaky tests.** A test that passes 9 times out of 10 is broken. Fix or remove.
2. **No tests against live external APIs.** Use VCR cassettes or `responses` mocks. Live external tests are a separate, manually-triggered job.
3. **Test data is generated, not stored.** Factories for users, drugs, symptoms — never fixtures committed as files.
4. **Bilingual coverage.** E2E tests run in both Arabic and English. Add `for (const lang of ['en', 'ar'])` loops where text is checked.
