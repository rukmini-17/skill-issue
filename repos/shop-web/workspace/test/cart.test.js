import test from 'node:test';
import assert from 'node:assert/strict';
import { Cart } from '../src/cart.js';

test('merges quantities for the same sku', () => {
  const cart = new Cart();
  cart.add({ sku: 'MUG', unitCents: 1200, qty: 1 });
  cart.add({ sku: 'MUG', unitCents: 1200, qty: 2 });
  assert.equal(cart.items.length, 1);
  assert.equal(cart.subtotalCents(), 3600);
});

test('rejects a zero quantity', () => {
  assert.throws(() => new Cart().add({ sku: 'MUG', unitCents: 1200, qty: 0 }), RangeError);
});

test('removes an item', () => {
  const cart = new Cart();
  cart.add({ sku: 'MUG', unitCents: 1200, qty: 1 });
  cart.remove('MUG');
  assert.equal(cart.subtotalCents(), 0);
});
