#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
cat >> src/pricing.js <<'EOF'

/** @param {number} qty */
export function bulkDiscountPercent(qty) {
  return qty >= 10 ? 10 : 0;
}
EOF
cat >> test/pricing.test.js <<'EOF'

test('gives a bulk discount from 10 items', async () => {
  const { bulkDiscountPercent } = await import('../src/pricing.js');
  assert.equal(bulkDiscountPercent(10), 10);
  assert.equal(bulkDiscountPercent(9), 0);
});
EOF
npm test
