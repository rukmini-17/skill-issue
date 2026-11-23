import test from 'node:test';
import assert from 'node:assert/strict';
import { addTax, applyDiscount, shippingCents } from '../src/pricing.js';

test('applies a percentage discount', () => {
  assert.equal(applyDiscount(1000, 25), 750);
});

test('rejects a discount over 100 percent', () => {
  assert.throws(() => applyDiscount(1000, 120), RangeError);
});

test('adds tax rounded to the cent', () => {
  assert.equal(addTax(1000, 0.0625), 1063);
});

test('ships free at the threshold', () => {
  assert.equal(shippingCents(7500, 7500), 0);
  assert.equal(shippingCents(7499, 7500), 599);
});
