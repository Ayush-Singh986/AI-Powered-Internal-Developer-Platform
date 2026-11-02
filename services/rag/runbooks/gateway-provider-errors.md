# GatewayProviderErrors and GatewayErrorRate

## What this alert means

The LLM gateway has repeated failures calling the model-serving adapter or
provider.

## Investigation

1. Check gateway and model-serving health and recent error metrics.
2. Confirm provider availability, configured model, and credential validity.
3. Check DNS, network policy, request timeouts, and provider rate limits.
4. Review token-budget rejections separately from provider failures.

## Safe response

Do not rotate or print credentials in logs. Restore provider connectivity or
configuration first. A gateway restart is not a substitute for checking the
provider and its credentials.
