#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
cp "$1/files/src/cart.js" src/cart.js
cat >> test/cart.test.js <<'EOF'

test('rejects a negative price', () => {
  assert.throws(() => new Cart().add({ sku: 'MUG', unitCents: -1, qty: 1 }), RangeError);
});
EOF
npm test
