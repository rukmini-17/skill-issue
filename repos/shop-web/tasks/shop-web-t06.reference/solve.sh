#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
cp "$1/files/src/cart.js" src/cart.js
cat >> test/cart.test.js <<'EOF'

test('clears the cart', () => {
  const cart = new Cart();
  cart.add({ sku: 'MUG', unitCents: 1200, qty: 1 });
  cart.clear();
  assert.equal(cart.subtotalCents(), 0);
});
EOF
npm test
