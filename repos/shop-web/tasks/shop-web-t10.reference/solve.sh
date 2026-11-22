#!/bin/sh
# Reference solution. Runs in the workspace root; $1 is this folder.
set -e
sed -i "s/if (percent < 0 || percent > 100) {/if (!(percent >= 0 \&\& percent <= 100)) {/" src/pricing.js
cat >> test/pricing.test.js <<'EOF'

test('rejects a NaN discount', () => {
  assert.throws(() => applyDiscount(1000, NaN), RangeError);
});
EOF
npm test
