#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
sed -i "s|^    const existing = this.items.find|    if (item.unitCents < 0) {\n      throw new RangeError('unitCents must not be negative');\n    }\n    const existing = this.items.find|" src/cart.js
cat >> test/cart.test.js <<'EOF'

test('rejects a negative price', () => {
  assert.throws(() => new Cart().add({ sku: 'MUG', unitCents: -1, qty: 1 }), RangeError);
});
EOF
npm test
