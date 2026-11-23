import { applyDiscount } from '../src/pricing.js';

describe('applyDiscount', () => {
  it('should reduce the price by the given percent', () => {
    expect(applyDiscount(1000, 25)).toBe(750);
  });
});
