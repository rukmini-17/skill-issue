#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
sed -i "s|^  subtotalCents() {|  clear() {\n    this.items = [];\n  }\n\n  subtotalCents() {|" src/cart.js
cat >> test/cart.test.js <<'EOF'

test('clears the cart', () => {
  const cart = new Cart();
  cart.add({ sku: 'MUG', unitCents: 1200, qty: 1 });
  cart.clear();
  assert.equal(cart.subtotalCents(), 0);
});
EOF
npm test
