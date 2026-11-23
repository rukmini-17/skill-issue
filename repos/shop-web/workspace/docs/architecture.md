# Architecture

Harbor Shop is a small storefront API.

- `src/cart.js` holds cart state.
- `src/pricing.js` calculates discounts, tax and shipping.
- `src/payment-client.js` calls the payment provider.
- `src/server.js` exposes `POST /quote`.
